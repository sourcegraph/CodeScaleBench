```csharp
// -------------------------------------------------------------------------------------------------
//  CanvasCraft ML Studio
//  File: src/CanvasCraft.Api/Middleware/ErrorHandlerMiddleware.cs
//  Description:
//      Global exception‐handling middleware that converts unhandled exceptions into RFC 7807
//      problem responses with structured logging. It is aware of CanvasCraft domain exceptions
//      (e.g., ValidationException, NotFoundException, ConcurrencyException) and falls back to a
//      generic 500 response for unexpected errors.
// -------------------------------------------------------------------------------------------------
using System.Diagnostics;
using System.Net;
using System.Text.Json;
using CanvasCraft.Domain.Exceptions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Api.Middleware;

/// <summary>
/// ASP.NET Core middleware that handles all unhandled exceptions in the request pipeline,
/// logs them in a structured manner, and returns RFC 7807 compliant responses.
/// </summary>
public sealed class ErrorHandlerMiddleware
{
    private static readonly JsonSerializerOptions _jsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = false
    };

    private readonly RequestDelegate _next;
    private readonly ILogger<ErrorHandlerMiddleware> _logger;
    private readonly IHostEnvironment _environment;

    /// <summary>
    /// Initializes a new instance of <see cref="ErrorHandlerMiddleware" />.
    /// </summary>
    public ErrorHandlerMiddleware(
        RequestDelegate next,
        ILogger<ErrorHandlerMiddleware> logger,
        IHostEnvironment environment)
    {
        _next = next ?? throw new ArgumentNullException(nameof(next));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _environment = environment ?? throw new ArgumentNullException(nameof(environment));
    }

    /// <summary>
    /// Invokes the middleware for the specified <see cref="HttpContext" />.
    /// </summary>
    public async Task InvokeAsync(HttpContext context)
    {
        ArgumentNullException.ThrowIfNull(context);

        try
        {
            await _next(context);
        }
        catch (Exception ex)
        {
            await HandleExceptionAsync(context, ex).ConfigureAwait(false);
        }
    }

    #region Private helpers

    private async Task HandleExceptionAsync(HttpContext context, Exception exception)
    {
        string traceId = Activity.Current?.Id ?? context.TraceIdentifier;

        (ProblemDetails problem, HttpStatusCode statusCode) = MapException(exception, traceId);

        _logger.Log(
            statusCode >= HttpStatusCode.InternalServerError
                ? LogLevel.Error
                : LogLevel.Warning,
            exception,
            "Request {Method} {Path} failed with status code {StatusCode}. TraceId: {TraceId}",
            context.Request.Method,
            context.Request.Path,
            (int)statusCode,
            traceId);

        context.Response.StatusCode = (int)statusCode;
        context.Response.ContentType = "application/problem+json";

        await JsonSerializer.SerializeAsync(
                context.Response.Body,
                problem,
                _jsonOptions,
                context.RequestAborted)
            .ConfigureAwait(false);
    }

    private static (ProblemDetails problem, HttpStatusCode statusCode) MapException(
        Exception exception,
        string traceId)
    {
        HttpStatusCode statusCode;
        string title;
        string detail = exception.Message;

        switch (exception)
        {
            case ValidationException validationEx:
                statusCode = HttpStatusCode.UnprocessableEntity;
                title = "Validation failed for one or more inputs.";
                return (
                    new ValidationProblemDetails(validationEx.Errors)
                    {
                        Title = title,
                        Status = (int)statusCode,
                        Detail = detail,
                        Instance = traceId,
                        Type = "https://httpstatuses.com/422"
                    },
                    statusCode);

            case NotFoundException:
                statusCode = HttpStatusCode.NotFound;
                title = "The requested resource was not found.";
                break;

            case ConcurrencyException:
                statusCode = HttpStatusCode.Conflict;
                title = "The record you attempted to edit was modified by another user.";
                break;

            case DomainException:
                statusCode = HttpStatusCode.BadRequest;
                title = "A domain error has occurred.";
                break;

            default:
                statusCode = HttpStatusCode.InternalServerError;
                title = "An unexpected error has occurred.";
                break;
        }

        // In production, avoid leaking internal details
        if (statusCode == HttpStatusCode.InternalServerError)
        {
            detail = _jsonOptions.WriteIndented
                ? "See logs for more information."
                : "Internal Server Error.";
        }

        var problem = new ProblemDetails
        {
            Title = title,
            Status = (int)statusCode,
            Detail = detail,
            Instance = traceId,
            Type = $"https://httpstatuses.com/{(int)statusCode}"
        };

        return (problem, statusCode);
    }

    #endregion
}

/// <summary>
/// Extension helpers to wire up the <see cref="ErrorHandlerMiddleware" />.
/// </summary>
public static class ErrorHandlerMiddlewareExtensions
{
    /// <summary>
    /// Adds <see cref="ErrorHandlerMiddleware" /> to the application's request pipeline.
    /// Must be registered early to catch exceptions thrown by later middleware.
    /// </summary>
    public static IApplicationBuilder UseCanvasCraftErrorHandler(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);
        return app.UseMiddleware<ErrorHandlerMiddleware>();
    }
}
```
