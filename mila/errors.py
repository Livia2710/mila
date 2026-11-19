class MilaError(Exception):
    """Base class for controlled application errors."""


class KnowledgeBaseUnavailable(MilaError):
    pass


class LLMUnavailable(MilaError):
    pass


class LiveDataUnavailable(MilaError):
    pass


class TranscriptionUnavailable(MilaError):
    pass

