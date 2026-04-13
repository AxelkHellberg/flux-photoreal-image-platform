from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationMode(StrEnum):
    PHOTOREAL = "photoreal"


class AspectRatioPreset(StrEnum):
    SQUARE = "1:1"
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    PORTRAIT_CLASSIC = "4:5"
    PHOTO = "3:2"


class SeedStrategy(StrEnum):
    SAME = "same"
    NEW = "new"


class StorageBackendType(StrEnum):
    S3 = "s3"
    LOCAL = "local"


class GeneratorBackendType(StrEnum):
    STUB = "stub"
    FLUX = "flux"
