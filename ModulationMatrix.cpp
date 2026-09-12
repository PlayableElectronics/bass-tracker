#include <cmath>

#include "ModulationMatrix.h"

namespace bass
{
namespace
{
float Clamp(float value, float low, float high)
{
    return value < low ? low : (value > high ? high : value);
}

float Shape(float value, float curve)
{
    const float magnitude = std::fabs(value);
    if(curve > 0.0f)
        return value < 0.0f ? -std::pow(magnitude, 1.0f + curve * 3.0f)
                            : std::pow(magnitude, 1.0f + curve * 3.0f);
    if(curve < 0.0f)
    {
        const float exponent = 1.0f / (1.0f + (-curve) * 3.0f);
        return value < 0.0f ? -std::pow(magnitude, exponent)
                            : std::pow(magnitude, exponent);
    }
    return value;
}
} // namespace

void ModulationMatrix::Init()
{
    for(size_t i = 0; i < kMaxModulationRoutes; ++i)
        routes_[i] = {};
    for(size_t i = 0; i < kModulationDestinationCount; ++i)
        smoothed_[i] = 0.0f;
}

bool ModulationMatrix::SetRoute(size_t index, const ModulationRoute& route)
{
    if(index >= kMaxModulationRoutes || std::fabs(route.amount) > 1.0f
       || std::fabs(route.curve) > 1.0f || route.smoothing_seconds < 0.0f)
        return false;
    routes_[index] = route;
    return true;
}

const ModulationRoute& ModulationMatrix::GetRoute(size_t index) const
{
    static const ModulationRoute kEmpty = {};
    return index < kMaxModulationRoutes ? routes_[index] : kEmpty;
}

ModulationFrame ModulationMatrix::Process(const ExpressionFrame& expression,
                                          float frame_seconds)
{
    float target[kModulationDestinationCount] = {};
    for(size_t i = 0; i < kMaxModulationRoutes; ++i)
    {
        const ModulationRoute& route = routes_[i];
        if(!route.enabled)
            continue;
        const size_t destination = static_cast<size_t>(route.destination);
        const float source = GetExpressionValue(expression.normalized, route.source);
        target[destination] += route.amount * Shape(source, route.curve);
    }

    ModulationFrame frame = {};
    for(size_t i = 0; i < kModulationDestinationCount; ++i)
    {
        target[i] = Clamp(target[i], -1.0f, 1.0f);
        float alpha = 1.0f;
        // Per-destination smoothing is selected as the slowest active route.
        float smoothing = 0.0f;
        for(size_t route_index = 0; route_index < kMaxModulationRoutes; ++route_index)
        {
            const ModulationRoute& route = routes_[route_index];
            if(route.enabled && static_cast<size_t>(route.destination) == i
               && route.smoothing_seconds > smoothing)
                smoothing = route.smoothing_seconds;
        }
        if(smoothing > 0.0f && frame_seconds > 0.0f)
            alpha = 1.0f - std::exp(-frame_seconds / smoothing);
        smoothed_[i] += alpha * (target[i] - smoothed_[i]);
        frame.values[i] = smoothed_[i];
    }
    return frame;
}
} // namespace bass
