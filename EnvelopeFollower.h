#pragma once

#include "AnalysisTypes.h"

namespace bass
{
class EnvelopeFollower
{
  public:
    void Init(float sample_rate);
    void Process(float sample);
    SignalState ConsumeState();

  private:
    float envelope_ = 0.0f;
    float previous_envelope_ = 0.0f;
    float attack_ = 0.0f;
    float attack_coefficient_ = 0.0f;
    float release_coefficient_ = 0.0f;
    float attack_decay_coefficient_ = 0.0f;
    uint32_t gate_release_samples_ = 0;
    uint32_t gate_release_limit_ = 0;
    uint32_t onset_rearm_samples_ = 0;
    uint32_t onset_rearm_limit_ = 0;
    bool gate_ = false;
    bool onset_latched_ = false;
    bool onset_armed_ = true;
};
} // namespace bass
