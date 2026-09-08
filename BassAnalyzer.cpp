#include <cmath>
#include <cstddef>
#include <cstdint>

#include "daisy_seed.h"

using namespace daisy;

namespace
{
constexpr float kSampleRate       = 48000.0f;
constexpr size_t kAudioBlockSize  = 16;
constexpr size_t kDecimation      = 4;
constexpr float kAnalysisRate     = kSampleRate / kDecimation;
constexpr size_t kAnalysisWindow  = 512;
constexpr size_t kAnalysisHop     = 128;
constexpr size_t kMinLag          = 30;
constexpr size_t kMaxLag          = 400;
constexpr float kLowPassCutoff    = 1200.0f;
constexpr float kDcCoefficient    = 0.995f;
constexpr float kAttackSeconds    = 0.0015f;
constexpr float kReleaseSeconds   = 0.080f;
constexpr float kGateThreshold    = 0.003f;
constexpr size_t kBufferCount     = 3;

struct BassAnalysis
{
    float frequency_hz;
    float confidence;
    float envelope;
    float attack;
    bool gate;
};

struct AnalysisBlock
{
    float samples[kAnalysisWindow];
};

static DaisySeed hw;
static AnalysisBlock analysis_buffers[kBufferCount];
static float analysis_ring[kAnalysisWindow];
static volatile int ready_buffer = -1;
static volatile int processing_buffer = -1;
static size_t ring_write = 0;
static size_t decimated_samples = 0;

static float dc_previous_input = 0.0f;
static float dc_previous_output = 0.0f;
static float lowpass_state = 0.0f;
static float envelope_state = 0.0f;
static float previous_envelope = 0.0f;
static volatile float attack_measure = 0.0f;
static float decimation_accumulator = 0.0f;
static size_t decimation_count = 0;

static BassAnalysis latest = {0.0f, 0.0f, 0.0f, 0.0f, false};

float FollowerCoefficient(float time_seconds)
{
    return 1.0f - std::exp(-1.0f / (time_seconds * kSampleRate));
}

float LowPassCoefficient()
{
    return 1.0f - std::exp(-2.0f * 3.14159265359f * kLowPassCutoff
                            / kSampleRate);
}

void PublishAnalysis(const BassAnalysis& value)
{
    latest = value;
}

bool TakeAnalysisBlock(int& index)
{
    int candidate = ready_buffer;
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

void AnalyzeBlock(const float* samples)
{
    float best_corr = 0.0f;
    size_t best_lag = 0;

    for(size_t lag = kMinLag; lag <= kMaxLag; ++lag)
    {
        float xy = 0.0f;
        float xx = 0.0f;
        float yy = 0.0f;
        const size_t count = kAnalysisWindow - lag;
        for(size_t i = 0; i < count; ++i)
        {
            const float x = samples[i];
            const float y = samples[i + lag];
            xy += x * y;
            xx += x * x;
            yy += y * y;
        }

        const float denominator = std::sqrt(xx * yy);
        const float corr = denominator > 1.0e-12f ? xy / denominator : 0.0f;
        if(corr > best_corr)
        {
            best_corr = corr;
            best_lag = lag;
        }
    }

    BassAnalysis result;
    result.frequency_hz = best_lag > 0 ? kAnalysisRate / best_lag : 0.0f;
    result.confidence = best_corr;
    result.envelope = envelope_state;
    result.attack = attack_measure;
    result.gate = envelope_state >= kGateThreshold;
    PublishAnalysis(result);
    attack_measure = 0.0f;
}

void AudioCallback(AudioHandle::InterleavingInputBuffer in,
                   AudioHandle::InterleavingOutputBuffer out,
                   size_t size)
{
    const float lowpass_coefficient = LowPassCoefficient();
    const float attack_coefficient = FollowerCoefficient(kAttackSeconds);
    const float release_coefficient = FollowerCoefficient(kReleaseSeconds);

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
        const float magnitude = std::fabs(lowpass_state);
        const float coefficient = magnitude > envelope_state
                                      ? attack_coefficient
                                      : release_coefficient;
        previous_envelope = envelope_state;
        envelope_state += coefficient * (magnitude - envelope_state);
        const float rise = envelope_state - previous_envelope;
        if(rise > attack_measure)
            attack_measure = rise;

        decimation_accumulator += lowpass_state;
        ++decimation_count;
        if(decimation_count == kDecimation)
        {
            const float sample = decimation_accumulator / kDecimation;
            decimation_accumulator = 0.0f;
            decimation_count = 0;

            analysis_ring[ring_write] = sample;
            ring_write = (ring_write + 1) % kAnalysisWindow;
            ++decimated_samples;
            if(decimated_samples >= kAnalysisWindow
               && decimated_samples % kAnalysisHop == 0
               && ready_buffer < 0)
            {
                int candidate = -1;
                for(int i = 0; i < static_cast<int>(kBufferCount); ++i)
                {
                    if(i != processing_buffer)
                    {
                        candidate = i;
                        break;
                    }
                }
                if(candidate >= 0)
                {
                    for(size_t i = 0; i < kAnalysisWindow; ++i)
                        analysis_buffers[candidate].samples[i]
                            = analysis_ring[(ring_write + i) % kAnalysisWindow];
                    ready_buffer = candidate;
                }
            }
        }
    }
}
} // namespace

int main(void)
{
    hw.Init();
    hw.SetAudioBlockSize(kAudioBlockSize);
    hw.StartLog(false);
    hw.StartAudio(AudioCallback);

    hw.PrintLine("BassAnalyzer 48kHz block=16 decimation=4 window=512 hop=128");
    hw.PrintLine("range=30-400 lpf=1200Hz gate=0.003");

    uint32_t next_report = System::GetNow();
    while(1)
    {
        int index = -1;
        if(TakeAnalysisBlock(index))
        {
            AnalyzeBlock(analysis_buffers[index].samples);
            ReleaseAnalysisBlock(index);
        }

        const uint32_t now = System::GetNow();
        if(static_cast<uint32_t>(now - next_report) >= 50)
        {
            next_report = now;
            const BassAnalysis snapshot = latest;
            hw.PrintLine("F=" FLT_FMT(2) "  CONF=" FLT_FMT3 "  ENV=" FLT_FMT3
                         "  ATT=" FLT_FMT3 "  G=%d",
                         FLT_VAR(2, snapshot.frequency_hz),
                         FLT_VAR3(snapshot.confidence),
                         FLT_VAR3(snapshot.envelope),
                         FLT_VAR3(snapshot.attack),
                         snapshot.gate ? 1 : 0);
        }
    }
}
