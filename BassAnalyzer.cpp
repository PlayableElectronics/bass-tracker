#include <cmath>
#include <cstddef>
#include <cstdint>

#include "daisy_seed.h"

#include "AnalysisTypes.h"
#include "EnvelopeFollower.h"
#include "PitchDetector.h"
#include "PitchTracker.h"

using namespace daisy;

namespace
{
constexpr float kSampleRate = 48000.0f;
constexpr size_t kAudioBlockSize = 16;
constexpr size_t kDecimation = 4;
constexpr float kAnalysisRate = kSampleRate / kDecimation;
constexpr size_t kAnalysisWindow = 512;
constexpr size_t kAnalysisHop = 128;
constexpr size_t kBufferCount = 3;
constexpr float kLowPassCutoff = 1200.0f;
constexpr float kDcCoefficient = 0.995f;

struct AnalysisBlock
{
    float samples[kAnalysisWindow];
    bass::SignalState signal;
    uint32_t sequence;
    uint32_t ms;
};

static DaisySeed hw;
static AnalysisBlock analysis_buffers[kBufferCount];
static float analysis_ring[kAnalysisWindow];
static volatile int ready_buffer = -1;
static volatile int processing_buffer = -1;
static size_t ring_write = 0;
static uint32_t decimated_samples = 0;
static uint32_t produced_sequence = 0;

static float dc_previous_input = 0.0f;
static float dc_previous_output = 0.0f;
static float lowpass_state = 0.0f;
static float decimation_accumulator = 0.0f;
static size_t decimation_count = 0;
static bass::EnvelopeFollower envelope_follower;
static bass::PitchTracker pitch_tracker;

float LowPassCoefficient()
{
    return 1.0f - std::exp(-2.0f * 3.14159265359f * kLowPassCutoff
                            / kSampleRate);
}

bool TakeAnalysisBlock(int& index)
{
    const int candidate = ready_buffer;
    if(candidate < 0)
        return false;
    ready_buffer = -1;
    processing_buffer = candidate;
    index = candidate;
    return true;
}

void ReleaseAnalysisBlock(int index)
{
    if(processing_buffer == index)
        processing_buffer = -1;
}

void PrintCsvHeader()
{
    hw.Print("seq,ms,raw_freq_hz,tracked_freq_hz,raw_confidence,");
    hw.Print("tracked_confidence,envelope,attack,gate,pitch_valid,onset,");
    hw.PrintLine("c1_freq,c1_score,c2_freq,c2_score,c3_freq,c3_score,c4_freq,c4_score");
}

void PrintCsvRow(const bass::BassAnalysis& analysis)
{
    const bass::PitchCandidate empty = {0.0f, 0.0f, 0};
    const bass::PitchCandidate& c1 = analysis.candidate_count > 0
                                         ? analysis.candidates[0] : empty;
    const bass::PitchCandidate& c2 = analysis.candidate_count > 1
                                         ? analysis.candidates[1] : empty;
    const bass::PitchCandidate& c3 = analysis.candidate_count > 2
                                         ? analysis.candidates[2] : empty;
    const bass::PitchCandidate& c4 = analysis.candidate_count > 3
                                         ? analysis.candidates[3] : empty;

    // libDaisy has a 128-byte logger buffer. Emit one CSV record in safe chunks.
    hw.Print("%lu,%lu," FLT_FMT(2) "," FLT_FMT(2) "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 ",",
             static_cast<unsigned long>(analysis.sequence),
             static_cast<unsigned long>(analysis.ms),
             FLT_VAR(2, analysis.raw_frequency_hz),
             FLT_VAR(2, analysis.tracked_frequency_hz),
             FLT_VAR3(analysis.raw_confidence),
             FLT_VAR3(analysis.tracked_confidence),
             FLT_VAR3(analysis.envelope));
    hw.Print(FLT_FMT3 ",%d,%d,%d,",
             FLT_VAR3(analysis.attack),
             analysis.gate ? 1 : 0,
             analysis.pitch_valid ? 1 : 0,
             analysis.onset ? 1 : 0);
    hw.Print(FLT_FMT(2) "," FLT_FMT3 "," FLT_FMT(2) "," FLT_FMT3 ",",
             FLT_VAR(2, c1.frequency_hz), FLT_VAR3(c1.score),
             FLT_VAR(2, c2.frequency_hz), FLT_VAR3(c2.score));
    hw.PrintLine(FLT_FMT(2) "," FLT_FMT3 "," FLT_FMT(2) "," FLT_FMT3,
                 FLT_VAR(2, c3.frequency_hz), FLT_VAR3(c3.score),
                 FLT_VAR(2, c4.frequency_hz), FLT_VAR3(c4.score));
}

void AnalyzeBlock(const AnalysisBlock& block)
{
    bass::BassAnalysis result = {};
    result.sequence = block.sequence;
    result.ms = block.ms;
    result.envelope = block.signal.envelope;
    result.attack = block.signal.attack;
    result.gate = block.signal.gate;
    result.onset = block.signal.onset;
    result.candidate_count = bass::PitchDetector::Detect(block.samples,
                                                          kAnalysisWindow,
                                                          kAnalysisRate,
                                                          result.candidates,
                                                          bass::kMaxPitchCandidates);
    if(result.candidate_count > 0)
    {
        result.raw_frequency_hz = result.candidates[0].frequency_hz;
        result.raw_confidence = result.candidates[0].score;
    }

    const bass::PitchTrackResult tracked = pitch_tracker.Update(result.candidates,
                                                                 result.candidate_count,
                                                                 block.signal);
    result.tracked_frequency_hz = tracked.frequency_hz;
    result.tracked_confidence = tracked.confidence;
    result.pitch_valid = tracked.valid;
    PrintCsvRow(result);
}

void AudioCallback(AudioHandle::InterleavingInputBuffer in,
                   AudioHandle::InterleavingOutputBuffer out,
                   size_t size)
{
    const float lowpass_coefficient = LowPassCoefficient();
    for(size_t i = 0; i < size; i += 2)
    {
        const float input = in[i];
        out[i] = input;
        out[i + 1] = input;

        const float dc_blocked = input - dc_previous_input
                                 + kDcCoefficient * dc_previous_output;
        dc_previous_input = input;
        dc_previous_output = dc_blocked;
        lowpass_state += lowpass_coefficient * (dc_blocked - lowpass_state);
        envelope_follower.Process(lowpass_state);

        decimation_accumulator += lowpass_state;
        ++decimation_count;
        if(decimation_count != kDecimation)
            continue;

        analysis_ring[ring_write] = decimation_accumulator / kDecimation;
        ring_write = (ring_write + 1) % kAnalysisWindow;
        decimation_accumulator = 0.0f;
        decimation_count = 0;
        ++decimated_samples;

        if(decimated_samples < kAnalysisWindow
           || decimated_samples % kAnalysisHop != 0)
            continue;

        ++produced_sequence;
        if(ready_buffer >= 0)
            continue;

        int candidate = -1;
        for(int i = 0; i < static_cast<int>(kBufferCount); ++i)
        {
            if(i != processing_buffer)
            {
                candidate = i;
                break;
            }
        }
        if(candidate < 0)
            continue;

        AnalysisBlock& block = analysis_buffers[candidate];
        for(size_t i = 0; i < kAnalysisWindow; ++i)
            block.samples[i] = analysis_ring[(ring_write + i) % kAnalysisWindow];
        block.signal = envelope_follower.ConsumeState();
        block.sequence = produced_sequence;
        block.ms = static_cast<uint32_t>((static_cast<uint64_t>(decimated_samples)
                                          * 1000u) / kAnalysisRate);
        ready_buffer = candidate;
    }
}
} // namespace

int main(void)
{
    hw.Init();
    hw.SetAudioBlockSize(kAudioBlockSize);
    envelope_follower.Init(kSampleRate);
    pitch_tracker.Init();
    hw.StartLog(false);
    PrintCsvHeader();
    hw.StartAudio(AudioCallback);

    while(1)
    {
        int index = -1;
        if(TakeAnalysisBlock(index))
        {
            AnalyzeBlock(analysis_buffers[index]);
            ReleaseAnalysisBlock(index);
        }
    }
}
