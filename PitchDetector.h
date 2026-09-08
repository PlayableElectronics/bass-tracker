#pragma once

#include <cstddef>

#include "AnalysisTypes.h"

namespace bass
{
class PitchDetector
{
  public:
    static size_t Detect(const float* samples,
                         size_t sample_count,
                         float sample_rate,
                         PitchCandidate* candidates,
                         size_t candidate_capacity);
};
} // namespace bass
