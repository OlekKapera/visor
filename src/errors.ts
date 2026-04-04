import type { ErrorCode, ErrorPayload } from './types.js';

export function makeError(
  code: ErrorCode,
  message: string,
  likelyCause: string,
  nextStep: string
): ErrorPayload {
  return {
    code,
    message,
    likely_cause: likelyCause,
    next_step: nextStep
  };
}
