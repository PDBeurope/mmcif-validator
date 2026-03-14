/**
 * Types matching the Python protocol (protocol.py) for extension–script communication.
 * Keep in sync with protocol.py for validation results and script failure responses.
 */

export interface ValidationErrorItem {
    line: number;
    item: string;
    message: string;
    severity: string;
    column?: number;
    start_char?: number;
    end_char?: number;
}

export interface DepositionMissingItem {
    category: string;
    item: string;
    row_index?: number;
    row_key?: string;
    has_validation_error?: boolean;
}

export interface MetadataCompleteness {
    percentage: number;
    filled_count: number;
    total_count: number;
    method_detected?: string | null;
    message?: string | null;
    missing_categories?: string[];
    missing_items?: DepositionMissingItem[];
}

export interface ValidationResult {
    errors: ValidationErrorItem[];
    metadata_completeness?: MetadataCompleteness;
}

export interface ScriptFailure {
    success: false;
    error_code: number;
    message: string;
}

/** Script failure error codes; must match Python protocol.ErrorCode */
export const ErrorCode = {
    DICT_NOT_FOUND: 1,
    CIF_NOT_FOUND: 2,
    DOWNLOAD_ERROR: 3,
    UNKNOWN_ERROR: 99,
} as const;

export function isScriptFailure(obj: unknown): obj is ScriptFailure {
    return (
        typeof obj === 'object' &&
        obj !== null &&
        'success' in obj &&
        (obj as ScriptFailure).success === false &&
        typeof (obj as ScriptFailure).error_code === 'number' &&
        typeof (obj as ScriptFailure).message === 'string'
    );
}

export function isValidationResult(obj: unknown): obj is ValidationResult {
    return (
        typeof obj === 'object' &&
        obj !== null &&
        'errors' in obj &&
        Array.isArray((obj as ValidationResult).errors)
    );
}
