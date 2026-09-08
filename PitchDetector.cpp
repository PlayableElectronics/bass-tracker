#include <cmath>

#include "PitchDetector.h"

namespace bass
{
namespace
{
constexpr size_t kMinimumLag = 30;
constexpr size_t kMaximumLag = 400;
constexpr size_t kLagCount = kMaximumLag - kMinimumLag + 1;

void InsertCandidate(PitchCandidate candidate,
                     PitchCandidate* candidates,
                     size_t capacity,
                     size_t& count)
{
    if(candidate.score <= 0.0f)
        return;

    size_t insert_at = count;
    for(size_t i = 0; i < count; ++i)
    {
        if(candidate.score > candidates[i].score)
        {
            insert_at = i;
            break;
        }
    }
    if(insert_at >= capacity)
        return;

    const size_t last = count < capacity ? count : capacity - 1;
    for(size_t i = last; i > insert_at; --i)
        candidates[i] = candidates[i - 1];
    candidates[insert_at] = candidate;
    if(count < capacity)
        ++count;
}
} // namespace

size_t PitchDetector::Detect(const float* samples,
                             size_t sample_count,
                             float sample_rate,
                             PitchCandidate* candidates,
                             size_t candidate_capacity)
{
    if(sample_count <= kMaximumLag || candidate_capacity == 0)
        return 0;

    float correlations[kLagCount];
    for(size_t offset = 0; offset < kLagCount; ++offset)
    {
        const size_t lag = kMinimumLag + offset;
        const size_t count = sample_count - lag;
        float xy = 0.0f;
        float xx = 0.0f;
        float yy = 0.0f;
        for(size_t i = 0; i < count; ++i)
        {
            const float x = samples[i];
            const float y = samples[i + lag];
            xy += x * y;
            xx += x * x;
            yy += y * y;
        }
        const float denominator = std::sqrt(xx * yy);
        correlations[offset] = denominator > 1.0e-12f ? xy / denominator : 0.0f;
    }

    size_t candidate_count = 0;
    for(size_t offset = 1; offset + 1 < kLagCount; ++offset)
    {
        const float score = correlations[offset];
        if(score >= correlations[offset - 1] && score > correlations[offset + 1])
        {
            const size_t lag = kMinimumLag + offset;
            InsertCandidate({sample_rate / lag, score, lag},
                            candidates,
                            candidate_capacity,
                            candidate_count);
        }
    }

    if(candidate_count == 0)
    {
        size_t best_offset = 0;
        for(size_t offset = 1; offset < kLagCount; ++offset)
        {
            if(correlations[offset] > correlations[best_offset])
                best_offset = offset;
        }
        const size_t lag = kMinimumLag + best_offset;
        InsertCandidate({sample_rate / lag, correlations[best_offset], lag},
                        candidates,
                        candidate_capacity,
                        candidate_count);
    }
    return candidate_count;
}
} // namespace bass
