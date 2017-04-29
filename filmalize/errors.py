"""Custom error classes for filmalize."""


class Error(Exception):
    """Base class for filmalize Exceptions."""

    pass


class ProbeError(Error):
    """Custom Exception for when ffprobe is unable to parse a file."""

    def __init__(self, file_name, message=None):
        self.file_name = file_name
        self.message = message if message else ''


class UserCancelError(Error):
    """Custom Exception for when the user cancels an action."""

    def __init__(self, message=None):
        self.message = message if message else ''


class ProgressFinishedError(Error):
    """Custom Exception for when a container has finished processing."""

    pass

class NoProgressError(Error):
    """Custom Exception for when we are unable to track the transcoding
    progress of a container."""

    pass
