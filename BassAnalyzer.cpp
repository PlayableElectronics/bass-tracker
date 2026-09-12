#include <cmath>
#include <cstdarg>
#include <cstddef>
#include <cstdint>
#include <cstdio>

#include "daisy_seed.h"
#include "hid/usb.h"
#include "sys/system.h"

#include "AnalysisTypes.h"
#include "EnvelopeFollower.h"
#include "ExpressionBus.h"
#include "ExpressionCalibration.h"
#include "ExpressionMidiProtocol.h"
#include "ModulationMatrix.h"
#include "PitchDetector.h"
#include "PitchTracker.h"

#ifndef BASS_EXPRESSION_USB_MIDI
#define BASS_EXPRESSION_USB_MIDI 0
#endif

#if BASS_EXPRESSION_USB_MIDI
#include "hid/midi.h"
#endif

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
constexpr float kAnalysisFrameSeconds = static_cast<float>(kAnalysisHop) / kAnalysisRate;
constexpr uint32_t kExpressionLogDivider = 8;
constexpr uint32_t kExpressionMidiDivider = 10;

struct AnalysisBlock
{
    float samples[kAnalysisWindow];
    bass::SignalState signal;
    float input_peak;
    float input_rms;
    float filtered_peak;
    float filtered_rms;
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
static float hop_input_peak = 0.0f;
static float hop_input_sum_squares = 0.0f;
static float hop_filtered_peak = 0.0f;
static float hop_filtered_sum_squares = 0.0f;
static size_t hop_sample_count = 0;
static bass::EnvelopeFollower envelope_follower;
static bass::PitchTracker pitch_tracker;
static bass::ExpressionAnalyzer expression_analyzer;
static bass::ExpressionCalibration expression_calibration;
static bass::ModulationMatrix modulation_matrix;
static bass::ExpressionMidiProtocol expression_midi_protocol;
static volatile float monitor_frequency_hz = 0.0f;
static volatile bool monitor_pitch_valid = false;
static float monitor_phase = 0.0f;
static float monitor_gain = 0.0f;

#if BASS_EXPRESSION_USB_MIDI
static MidiUsbHandler expression_midi;
#endif

// Logger::Print uses a 128-byte asynchronous buffer.  A full diagnostic CSV
// record is larger than that, so sending it in Logger chunks corrupts records
// when a USB transfer is still active.  These two buffers are alternated: when
// the next transfer is accepted, the prior buffer is no longer in use by USB.
#if !BASS_EXPRESSION_USB_MIDI
class CsvUsbLogger
{
  public:
    static void PrintLine(const char* format, ...)
    {
        char* buffer = buffers_[next_buffer_];
        va_list args;
        va_start(args, format);
        const int written = std::vsnprintf(buffer, kBufferSize - 2, format, args);
        va_end(args);

        size_t length = written > 0 ? static_cast<size_t>(written) : 0;
        if(length > kBufferSize - 2)
            length = kBufferSize - 2;
        buffer[length++] = '\r';
        buffer[length++] = '\n';

        // CSV diagnostics must never stall pitch analysis. When USB is not
        // being read, or a previous transfer is still active, drop this row
        // and leave the current buffer untouched for the pending transfer.
        if(usb_.TransmitInternal(reinterpret_cast<uint8_t*>(buffer), length)
           != UsbHandle::Result::OK)
            return;
        next_buffer_ = (next_buffer_ + 1) % kBufferCount;
    }

  private:
    static constexpr size_t kBufferCount = 2;
    static constexpr size_t kBufferSize = 384;
    static UsbHandle usb_;
    static char buffers_[kBufferCount][kBufferSize];
    static size_t next_buffer_;
};

UsbHandle CsvUsbLogger::usb_;
char CsvUsbLogger::buffers_[CsvUsbLogger::kBufferCount][CsvUsbLogger::kBufferSize];
size_t CsvUsbLogger::next_buffer_ = 0;
#endif

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

#if !BASS_EXPRESSION_USB_MIDI
void PrintCsvHeader()
{
    CsvUsbLogger::PrintLine("seq,ms,raw_freq_hz,tracked_freq_hz,raw_confidence,"
                            "tracked_confidence,envelope,attack,gate,pitch_valid,onset,"
                            "input_peak,input_rms,filtered_peak,filtered_rms,"
                            "c1_freq,c1_score,c2_freq,c2_score,c3_freq,c3_score,c4_freq,c4_score,"
                            "pre_stability_freq_hz,final_tracked_freq_hz,family_promoted,stability_bypass");
}

void PrintExpressionHeader()
{
    CsvUsbLogger::PrintLine(
        "expr,seq,ms,calibration_state,amp_raw,attack_raw,brightness_raw,periodicity_raw,"
        "tracker_conf_raw,competition_raw,octave_tension_raw,noise_raw,decay_raw,"
        "motion_raw,instability_raw,amp_norm,attack_norm,brightness_norm,periodicity_norm,"
        "tracker_conf_norm,competition_norm,octave_tension_norm,noise_norm,decay_norm,"
        "motion_norm,instability_norm");
}

void PrintExpressionRow(const bass::BassAnalysis& analysis)
{
    if(analysis.sequence % kExpressionLogDivider != 0)
        return;
    const bass::ExpressionValues& raw = analysis.expression.raw;
    const bass::ExpressionValues& normalized = analysis.expression.normalized;
    const bass::CalibrationStatus status = expression_calibration.Status();
    CsvUsbLogger::PrintLine(
        "expr,%lu,%lu,%d,"
        FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 ","
        FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 ","
        FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 ","
        FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3 ","
        FLT_FMT3 "," FLT_FMT3 "," FLT_FMT3,
        static_cast<unsigned long>(analysis.sequence),
        static_cast<unsigned long>(analysis.ms),
        static_cast<int>(status.state),
        FLT_VAR3(raw.values[0]), FLT_VAR3(raw.values[1]), FLT_VAR3(raw.values[2]),
        FLT_VAR3(raw.values[3]), FLT_VAR3(raw.values[4]), FLT_VAR3(raw.values[5]),
        FLT_VAR3(raw.values[6]), FLT_VAR3(raw.values[7]), FLT_VAR3(raw.values[8]),
        FLT_VAR3(raw.values[9]), FLT_VAR3(raw.values[10]),
        FLT_VAR3(normalized.values[0]), FLT_VAR3(normalized.values[1]),
        FLT_VAR3(normalized.values[2]), FLT_VAR3(normalized.values[3]),
        FLT_VAR3(normalized.values[4]), FLT_VAR3(normalized.values[5]),
        FLT_VAR3(normalized.values[6]), FLT_VAR3(normalized.values[7]),
        FLT_VAR3(normalized.values[8]), FLT_VAR3(normalized.values[9]),
        FLT_VAR3(normalized.values[10]));
}
#endif

#if BASS_EXPRESSION_USB_MIDI
void EmitExpressionMidi(const bass::BassAnalysis& analysis)
{
    if(analysis.sequence % kExpressionMidiDivider != 0)
        return;
    uint8_t bytes[96] = {};
    const size_t size = expression_midi_protocol.BuildTelemetry(
        analysis.expression, expression_calibration.Status(), bytes, sizeof(bytes));
    if(size > 0)
        expression_midi.SendMessage(bytes, size);
}

void ProcessExpressionMidiControls()
{
    expression_midi.Listen();
    while(expression_midi.HasEvents())
    {
        MidiEvent event = expression_midi.PopEvent();
        if(event.type != ControlChange)
            continue;
        const ControlChangeEvent control = event.AsControlChange();
        expression_midi_protocol.HandleControlChange(
            static_cast<uint8_t>(control.channel), control.control_number,
            control.value, expression_calibration);
    }
}
#endif

#if !BASS_EXPRESSION_USB_MIDI
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

    CsvUsbLogger::PrintLine(
        "%lu,%lu," FLT_FMT(2) "," FLT_FMT(2) "," FLT_FMT3 "," FLT_FMT3 ","
        FLT_FMT(6) "," FLT_FMT(6) ",%d,%d,%d,"
        FLT_FMT(6) "," FLT_FMT(6) "," FLT_FMT(6) "," FLT_FMT(6) ","
        FLT_FMT(2) "," FLT_FMT3 "," FLT_FMT(2) "," FLT_FMT3 ","
        FLT_FMT(2) "," FLT_FMT3 "," FLT_FMT(2) "," FLT_FMT3 ","
        FLT_FMT(2) "," FLT_FMT(2) ",%d,%d",
        static_cast<unsigned long>(analysis.sequence),
        static_cast<unsigned long>(analysis.ms),
        FLT_VAR(2, analysis.raw_frequency_hz),
        FLT_VAR(2, analysis.tracked_frequency_hz),
        FLT_VAR3(analysis.raw_confidence),
        FLT_VAR3(analysis.tracked_confidence),
        FLT_VAR(6, analysis.envelope),
        FLT_VAR(6, analysis.attack),
        analysis.gate ? 1 : 0,
        analysis.pitch_valid ? 1 : 0,
        analysis.onset ? 1 : 0,
        FLT_VAR(6, analysis.input_peak),
        FLT_VAR(6, analysis.input_rms),
        FLT_VAR(6, analysis.filtered_peak),
        FLT_VAR(6, analysis.filtered_rms),
        FLT_VAR(2, c1.frequency_hz),
        FLT_VAR3(c1.score),
        FLT_VAR(2, c2.frequency_hz),
        FLT_VAR3(c2.score),
        FLT_VAR(2, c3.frequency_hz),
        FLT_VAR3(c3.score),
        FLT_VAR(2, c4.frequency_hz),
        FLT_VAR3(c4.score),
        FLT_VAR(2, analysis.pre_stability_frequency_hz),
        FLT_VAR(2, analysis.tracked_frequency_hz),
        analysis.family_promoted ? 1 : 0,
        analysis.stability_bypass ? 1 : 0);
}
#endif

void AnalyzeBlock(const AnalysisBlock& block)
{
    bass::BassAnalysis result = {};
    result.sequence = block.sequence;
    result.ms = block.ms;
    result.envelope = block.signal.envelope;
    result.attack = block.signal.attack;
    result.input_peak = block.input_peak;
    result.input_rms = block.input_rms;
    result.filtered_peak = block.filtered_peak;
    result.filtered_rms = block.filtered_rms;
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
    result.pre_stability_frequency_hz = tracked.pre_stability_frequency_hz;
    result.tracked_confidence = tracked.confidence;
    result.pitch_valid = tracked.valid;
    result.family_promoted = tracked.family_promoted;
    result.stability_bypass = tracked.stability_bypass;
    result.expression = expression_analyzer.Update(
        result.sequence, result.ms, tracked.frequency_hz,
        tracked.pre_stability_frequency_hz, tracked.confidence, tracked.valid,
        result.candidates, result.candidate_count, block.signal,
        block.input_rms, block.filtered_rms);
    expression_calibration.Update(result.expression.raw, kAnalysisFrameSeconds);
    result.expression.normalized = expression_calibration.Normalize(result.expression.raw);
    // No routes are active in this milestone. Processing the fixed-size matrix
    // here verifies its real-time boundary without introducing a synth engine.
    modulation_matrix.Process(result.expression, kAnalysisFrameSeconds);
    monitor_frequency_hz = tracked.frequency_hz;
    monitor_pitch_valid = tracked.valid;
#if BASS_EXPRESSION_USB_MIDI
    EmitExpressionMidi(result);
#else
    PrintCsvRow(result);
    PrintExpressionRow(result);
#endif
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

        const float target_gain = monitor_pitch_valid ? 0.15f : 0.0f;
        monitor_gain += 0.002f * (target_gain - monitor_gain);

        float freq = monitor_frequency_hz;
        if(freq < 20.0f || freq > 500.0f)
            freq = 0.0f;

        if(freq > 0.0f)
        {
            monitor_phase += freq / kSampleRate;
            if(monitor_phase >= 1.0f)
                monitor_phase -= 1.0f;
        }

        const float sine = std::sin(2.0f * 3.14159265359f * monitor_phase)
                           * monitor_gain;
        out[i + 1] = sine;
        const float input_magnitude = std::fabs(input);
        if(input_magnitude > hop_input_peak)
            hop_input_peak = input_magnitude;
        hop_input_sum_squares += input * input;
        ++hop_sample_count;

        const float dc_blocked = input - dc_previous_input
                                 + kDcCoefficient * dc_previous_output;
        dc_previous_input = input;
        dc_previous_output = dc_blocked;
        lowpass_state += lowpass_coefficient * (dc_blocked - lowpass_state);
        const float filtered_magnitude = std::fabs(lowpass_state);
        if(filtered_magnitude > hop_filtered_peak)
            hop_filtered_peak = filtered_magnitude;
        hop_filtered_sum_squares += lowpass_state * lowpass_state;
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
        if(ready_buffer < 0)
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
                AnalysisBlock& block = analysis_buffers[candidate];
                for(size_t i = 0; i < kAnalysisWindow; ++i)
                    block.samples[i] = analysis_ring[(ring_write + i) % kAnalysisWindow];
                block.signal = envelope_follower.ConsumeState();
                block.input_peak = hop_input_peak;
                block.input_rms = hop_sample_count > 0
                                      ? std::sqrt(hop_input_sum_squares / hop_sample_count)
                                      : 0.0f;
                block.filtered_peak = hop_filtered_peak;
                block.filtered_rms = hop_sample_count > 0
                                         ? std::sqrt(hop_filtered_sum_squares / hop_sample_count)
                                         : 0.0f;
                block.sequence = produced_sequence;
                block.ms = static_cast<uint32_t>((static_cast<uint64_t>(decimated_samples)
                                                  * 1000u) / kAnalysisRate);
                ready_buffer = candidate;
            }
        }
        hop_input_peak = 0.0f;
        hop_input_sum_squares = 0.0f;
        hop_filtered_peak = 0.0f;
        hop_filtered_sum_squares = 0.0f;
        hop_sample_count = 0;
    }
}
} // namespace

int main(void)
{
    hw.Init();
    hw.SetAudioBlockSize(kAudioBlockSize);
    envelope_follower.Init(kSampleRate);
    pitch_tracker.Init();
    expression_analyzer.Init();
    expression_calibration.Init();
    modulation_matrix.Init();
    expression_midi_protocol.Init();
#if BASS_EXPRESSION_USB_MIDI
    MidiUsbHandler::Config midi_config;
    expression_midi.Init(midi_config);
    expression_midi.StartReceive();
#else
    hw.StartLog(false);
    PrintCsvHeader();
    PrintExpressionHeader();
#endif
    hw.StartAudio(AudioCallback);

    while(1)
    {
#if BASS_EXPRESSION_USB_MIDI
        ProcessExpressionMidiControls();
#endif
        int index = -1;
        if(TakeAnalysisBlock(index))
        {
            AnalyzeBlock(analysis_buffers[index]);
            ReleaseAnalysisBlock(index);
        }
    }
}
