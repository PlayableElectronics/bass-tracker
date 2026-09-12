#pragma once

#include <cstddef>
#include <cstdint>

#include "ExpressionBus.h"

namespace bass
{
// These are deliberately abstract resynthesis controls, not parameters for a
// conventional FM/subtractive engine. A future sound engine may choose any
// subset and interpret them as it sees fit.
enum class ModulationDestination : uint8_t
{
    ExcitationComplexity = 0,
    SpectralDistribution,
    InstabilityInteraction,
    ModeCoupling,
    StochasticExcitation,
    ResonatorDamping,
    StructuralMorph,
    Count,
};

constexpr size_t kModulationDestinationCount
    = static_cast<size_t>(ModulationDestination::Count);
constexpr size_t kMaxModulationRoutes = 16;

struct ModulationRoute
{
    ExpressionFeature source = ExpressionFeature::Amplitude;
    ModulationDestination destination = ModulationDestination::ExcitationComplexity;
    float amount = 0.0f;       // -1..+1
    float curve = 0.0f;        // -1..+1: linear at zero, progressively concave/convex
    float smoothing_seconds = 0.0f;
    bool enabled = false;
};

struct ModulationFrame
{
    float values[kModulationDestinationCount] = {};
};

class ModulationMatrix
{
  public:
    void Init();
    bool SetRoute(size_t index, const ModulationRoute& route);
    const ModulationRoute& GetRoute(size_t index) const;
    ModulationFrame Process(const ExpressionFrame& expression, float frame_seconds);

  private:
    ModulationRoute routes_[kMaxModulationRoutes] = {};
    float smoothed_[kModulationDestinationCount] = {};
};
} // namespace bass
