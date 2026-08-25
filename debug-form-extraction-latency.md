# [OPEN] form-extraction-latency

## Symptom

`POST /api/v1/form-extractions` takes nearly 20 seconds to return.

## Hypotheses

1. The LLM upstream request accounts for most of the latency.
2. The dynamic field list or prompt size increases model processing time.
3. Request parsing or response parsing adds significant latency.
4. The client calls the endpoint more than once or adds another upstream call.
5. Upstream timeout, retry, or network instability causes the delay.

## Evidence

The endpoint performs one synchronous LLM `POST /chat/completions` request before returning. It creates a new `httpx.AsyncClient` for every request and has no retry logic. The request does not set an output token limit. Runtime instrumentation could not start in the current sandbox because Windows socket operations are restricted.

## Preliminary Analysis

The most likely latency source is upstream LLM inference and response generation. Dynamic forms with many fields require the model to generate `value`, `confidence`, and `evidence` for each field, which increases output size. Connection setup can add a smaller amount of time because the HTTP client is not reused.

## Status

Runtime evidence blocked by the local sandbox; production reproduction is pending.
