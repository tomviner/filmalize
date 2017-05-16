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

    pass


class ProgressFinishedError(Error):
    """Custom Exception for when a container has finished processing."""

    pass


