```hlsl
//--------------------------------------------------------------------------------------------------
// File:    SampleTransform.hlsl
// Project: PaletteStream ETL Canvas
// Desc:    GPU transformation shader invoked by ComputeSharp from C# code.
//          Each thread performs a set of configurable, per-element ETL operations that mimic the
//          “blending” of pigments on a digital canvas:
//
//              1. Optional scaling                                 (EnableScale)
//              2. Optional anonymization noise injection           (EnableNoise)
//              3. Optional threshold clamping + quality flagging   (EnableThreshold)
//
//          The shader is designed to be data-agnostic: any float4 payload is supported.
//          Channel usage is decided by the calling C# layer, but a conventional layout is:
//              X – primary metric
//              Y – secondary metric
//              Z – timestamp or ordinal
//              W – auxiliary / reserved
//
//          A companion QualityFlags UAV captures per-row data-quality indicators to integrate with
//          the ETL error-recovery and monitoring subsystems.
//
//          Author: PaletteStream ETL Canvas – GPU Transformer Team
//--------------------------------------------------------------------------------------------------
#ifndef SAMPLE_TRANSFORM_INCLUDED
#define SAMPLE_TRANSFORM_INCLUDED

//--------------------------------------------------------------------------------------------------
// Constant buffer – Parameters are hydrated by the Transformer orchestrator at runtime.
//--------------------------------------------------------------------------------------------------
cbuffer Constants : register(b0)
{
    float Scale;            // Multiplicative data scaling factor.
    float Threshold;        // Absolute value clamp threshold.
    float NoiseAmplitude;   // Max amplitude for noise injection (anonymization).
    uint  EnableThreshold;  // Non-zero => clamp & flag outliers.
    uint  EnableNoise;      // Non-zero => inject pseudo-random noise.
    uint  EnableScale;      // Non-zero => apply scaling.
    uint  Padding_;         // 16-byte packing alignment (unused).
};

//--------------------------------------------------------------------------------------------------
// Resources:
//  • t0  – Read-only source buffer.
//  • u0  – Write-only destination buffer (in-place supported if aliasing with t0).
//  • u1  – Write-only quality flag buffer (1 uint per element).
//--------------------------------------------------------------------------------------------------
StructuredBuffer<float4>     InputData    : register(t0);
RWStructuredBuffer<float4>   OutputData   : register(u0);
RWStructuredBuffer<uint>     QualityFlags : register(u1);

//--------------------------------------------------------------------------------------------------
// Pseudo-random number generator – hash-based, stateless, deterministic.
// Sufficient for anonymization noise without introducing external RNG state.
//--------------------------------------------------------------------------------------------------
static float HashNoise(uint id)
{
    // Numerical recipe: https://www.shadertoy.com/view/4dS3Wd
    uint m = id;
    m ^= m >> 16;
    m *= 0x7feb352d;
    m ^= m >> 15;
    m *= 0x846ca68b;
    m ^= m >> 16;
    return (m & 0x00FFFFFFu) / 16777216.0f; // Map to [0,1)
}

//--------------------------------------------------------------------------------------------------
// Compute shader – 1D dispatch, thread group size of 64.
// The ETL coordinator sizes the dispatch to match the element count.
//--------------------------------------------------------------------------------------------------
[numthreads(64, 1, 1)]
void CSMain(uint3 DTid : SV_DispatchThreadID)
{
    uint index = DTid.x;

    // Defensive bounds check — calling code may over-dispatch to match next power-of-two.
    if (index >= InputData.Length)
    {
        return;
    }

    //----------------------------------------------------------------------------------------------
    // Fetch & transform data point
    //----------------------------------------------------------------------------------------------
    float4 sample = InputData[index];      // Original “pigment”
    float  metric = sample.x;              // Working on X component by convention

    // 1. Scaling ----------------------------------------------------------------------------------
    if (EnableScale != 0)
    {
        metric *= Scale;
    }

    // 2. Noise injection (for anonymization) ------------------------------------------------------
    if (EnableNoise != 0 && NoiseAmplitude > 0.0f)
    {
        float n = HashNoise(index);
        n = n * 2.0f - 1.0f;               // Shift to [-1, 1]
        metric += n * NoiseAmplitude;
    }

    // 3. Threshold clamping & flagging ------------------------------------------------------------
    uint flag = 0;
    if (EnableThreshold != 0 && Threshold > 0.0f)
    {
        if (abs(metric) > Threshold)
        {
            metric = sign(metric) * Threshold;
            flag   = 1;                    // Flag as outlier for downstream QC
        }
    }

    //----------------------------------------------------------------------------------------------
    // Write-back
    //----------------------------------------------------------------------------------------------
    sample.x = metric;
    OutputData[index]   = sample;
    QualityFlags[index] = flag;
}

#endif // SAMPLE_TRANSFORM_INCLUDED
```