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
    {
        routes_[i] = {};
        smoothed_routes_[i] = 0.0f;
    }
}

bool ModulationMatrix::SetRoute(size_t index, const ModulationRoute& route)
{
    if(index >= kMaxModulationRoutes || std::fabs(route.amount) > 1.0f
       || std::fabs(route.curve) > 1.0f || route.smoothing_seconds < 0.0f)
        return false;
    routes_[index] = route;
    smoothed_routes_[index] = 0.0f;
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
        {
            smoothed_routes_[i] = 0.0f;
            continue;
        }
        const size_t destination = static_cast<size_t>(route.destination);
        const float source = GetExpressionValue(expression.normalized, route.source);
        const float route_target = route.amount * Shape(source, route.curve);
        float alpha = 1.0f;
        if(route.smoothing_seconds > 0.0f && frame_seconds > 0.0f)
            alpha = 1.0f - std::exp(-frame_seconds / route.smoothing_seconds);
        smoothed_routes_[i] += alpha * (route_target - smoothed_routes_[i]);
        target[destination] += smoothed_routes_[i];
    }

    ModulationFrame frame = {};
    for(size_t i = 0; i < kModulationDestinationCount; ++i)
    {
        target[i] = Clamp(target[i], -1.0f, 1.0f);
        frame.values[i] = target[i];
    }
    return frame;
}
} // namespace bass
