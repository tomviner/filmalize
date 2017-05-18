"""CLI classes for filmalize.

This module contains classes for use by the cli and menus modules as well as
core classes extended with additional functionality for command-line use.

"""

import click
import progressbar

from filmalize.models import Container, ContainerLabel, Stream, SubtitleFile
from filmalize.errors import ProbeError


class SelectStreams(click.ParamType):
    """Custom Click parameter type to set the selected streams for a
    Container.

    This class can be set as the type option in a :obj:`Click.prompt` or other
    click input and, with the :obj:`convert` method, will check the users input
    to ensure that the indexes that they have entered match a :obj:`Stream`
    in the :obj:`Container` specified at instantiation.

    Args:
        container (:obj:`Container`): The Container to check for Stream
            indexes.

    """

    def __init__(self, container):
        self.container = container

    def convert(self, value, param, ctx):
        """Attempt to set input indexes as Container.streams."""

        try:
            selected = [int(index) for index in value.strip().split(' ')]
        except (ValueError, TypeError):
            self.fail('Invalid input. Enter stream indexes separated by a '
                      'single space')

        try:
            self.container.selected = selected
        except ValueError as _e:
            self.fail(_e)


class Writer(object):
    """Writes messages to a specific line on the screen, defined at
    instantiation.

    Args:
        line (:obj:`int`): The line of the screen for this instance to write
            to.
        terminal (:obj:`blessed.terminal.Terminal`): Where to write.
        color (:obj:`str`, optional): The color to print in. Must conform to
            the blessed color function `format`_.

    Attributes:
        line (:obj:`int`): The line of the screen that this instance writes
            to.
        terminal (:obj:`blessed.terminal.Terminal`): Where to write.
        color (:obj:`str`): The color to print in.

    .. _format: http://blessed.readthedocs.io/en/latest/overview.html#colors
    """

    def __init__(self, line, terminal, color=None):

        self.line = line
        self.terminal = terminal
        self.color = color

    def write(self, message):
        """Write a message to the screen.

        The message is written to the :obj:`Writer.terminal`, on the
        :obj:`Writer.line`, and in :obj:`Writer.color`, if set.

        Args:
            message (:obj:`str`): The message to display

        """
        with self.terminal.location(x=0, y=self.line):
            if self.color:
                print(getattr(self.terminal, self.color)(message))
            else:
                print(message)

    @staticmethod
    def flush():
        """Pretend to flush as if :obj:`Writer` was a real file descriptor.

        :obj:`progressbar.bar.ProgressBar` objects expect to flush their file
        descriptors, but since we're actually printing to a
        :obj:`blessed.terminal.Terminal`, this method is needed to keep the
        progress bars happy.

        Returns:
            :obj:`bool`: True

        """
        return True


class ErrorWriter(object):
    """Write error messages in bright red to the bottom of a Terminal.

    Args:
        terminal (:obj:`blessed.terminal.Terminal`): Where to write.

    Attributes:
        terminal (:obj:`blessed.terminal.Terminal`): Where to write.
        line (:obj:`int`): The highest line to write to. Starts at the bottom
            of the screen and increments upward as additional messages are
            written.
        messages (:obj:`list` of :obj:`str`): The messages to write.

    """

    def __init__(self, terminal):

        self.terminal = terminal
        self.line = terminal.height - 1
        self.messages = []

    def write(self, message):
        """Add a message to the list and display all  messages at the bottom of
        the Terminal.

        As subsequent messages are written, earlier messages are moved upward.

        Args:
            message (:obj:`str`): The message to display.

        """

        self.messages.append(message)
        with self.terminal.location(x=0, y=self.line):
            for message in self.messages:
                print(self.terminal.red(message), self.terminal.clear_eol)
        self.line -= 1


class CliContainer(Container):
    """Multimedia container file object with CLI extensions.

    Args:
        writer (:obj:`Writer`, optional): Object with which to display the
            progress bar.
        pr_bar (:obj:`progressbar.bar.ProgressBar`, optional): Progress bar to
            display the progress of converting this container.
        **kwargs: :obj:`Container` arguments.

    Attributes:
        writer (:obj:`Writer`): Object with which to write.
        pr_bar (:obj:`progressbar.bar.ProgressBar`): Progress bar to write.

    """

    def __init__(self, writer=None, pr_bar=None, **kwargs):
        self.writer = writer
        self.pr_bar = pr_bar
        super().__init__(**kwargs)

    @classmethod
    def from_dict(cls, info):
        """Build a :obj:`CliContainer` from a given dictionary.

        Args:
            info (:obj:`dict`): Container information in dictionary format
                structured in the manner of ffprobe json output.

        Returns:
            :obj:`CliContainer`: Instance representing the given info.

        Raises:
            :obj:`ProbeError`: If the info does not contain a 'duraton' tag.

        """

        file_name = info['format']['filename']
        duration = float(info.get('format', {}).get('duration', 0))
        if not duration:
            raise ProbeError(file_name, 'File has no duration tag.')

        streams = [CliStream.from_dict(stream) for stream in info['streams']]
        labels = ContainerLabel.from_dict(info)

        return cls(file_name=file_name, duration=duration, streams=streams,
                   labels=labels)

    def add_progress(self, terminal, line_number, padding):
        """Build a :obj:`progressbar.bar.Progressbar` instance for this
        Container.

        Args:
            terminal (:obj:`blessed.terminal.Terminal`): Terminal to display
                to.
            line_number (:obj:`int`): The line number to display on.
            padding (:obj:`int`): The number of characters to pad the filename
                with.

        """

        label = '{name:{length}}'.format(name=self.file_name, length=padding)
        widgets = [label, ' | ', progressbar.Percentage(), ' ',
                   progressbar.Bar(), ' ', progressbar.ETA()]
        self.writer = Writer(line_number, terminal, 'red_on_black')
        self.pr_bar = progressbar.ProgressBar(
            max_value=self.microseconds, widgets=widgets, fd=self.writer)

    def display(self):
        """Echo a pretty representation of this Container."""
        click.secho('*** File: {} ***'.format(self.file_name), fg='magenta')
        if self.labels.title:
            click.secho('Title: {}'.format(self.labels.title), fg='cyan')

        file_description = ['Length: {}'.format(self.labels.length)]
        file_description.append('Size: {}MiB'.format(self.labels.size))
        file_description.append('Bitrate: {}Mib/s'.format(self.labels.bitrate))
        file_description.append('Container: {}'
                                .format(self.labels.container_format))
        click.echo(' | '.join(file_description))

        for stream in self.streams:
            stream.display()

        for sub_file in self.subtitle_files:
            sub_file.display()

    def display_conversion(self):
        """Echo a pretty representation of the conversion actions to perform on
        this Container."""

        click.clear()
        self.display()
        click.secho('Filmalize Actions:', fg='cyan', bold=True)
        for stream in self.streams:
            if stream.index in self.selected:
                header = 'Stream {}: '.format(stream.index)
                stream.build_options()
                info = stream.option_summary
                click.echo(click.style(header, fg='green', bold=True)
                           + click.style(info, fg='yellow'))
        for subtitle in self.subtitle_files:
            click.echo(
                click.style(subtitle.file_name + ': ', fg='green', bold=True)
                + click.style(subtitle.option_summary, fg='yellow')
            )
        click.secho('Output File: {}'.format(self.output_name), fg='magenta')

    def display_command(self):
        """Echo the current compiled command for this Container."""

        self.display_conversion()
        click.secho('Command:', fg='cyan', bold=True)
        click.echo(' '.join(self.build_command()))


class CliStream(Stream):
    """Multimedia stream object with CLI extensions.

    Args:
        **kwargs: :obj:`Stream` arguments.

    """

    def display(self):
        """Echo a pretty representation of this Stream."""

        stream_header = 'Stream {}:'.format(self.index)
        stream_info = [self.type, self.codec]
        stream_info.append(self.labels.language)
        stream_info.append(self.labels.default)
        click.echo('  ' + click.style(stream_header, fg='green', bold=True)
                   + ' ' + click.style(' '.join(stream_info), fg='yellow'))

        if self.labels.title:
            click.echo('    Title: {}'.format(self.labels.title))

        stream_specs = []
        if self.type == 'video':
            stream_specs.append('Resolution: {}'
                                .format(self.labels.resolution))
            stream_specs.append('Bitrate: {}Mib/s'.format(self.labels.bitrate))
        elif self.type == 'audio':
            stream_specs.append('Channels: {}'.format(self.labels.channels))
            stream_specs.append('Bitrate: {}Kib/s'.format(self.labels.bitrate))
        if stream_specs:
            click.echo('    ' + ' | '.join(stream_specs))


class CliSubFile(SubtitleFile):
    """Subtitle file object with CLI extensions.

    Args:
        **kwargs: :obj:`SubtitleFile` arguments.

    """

    def display(self):
        """Echo a pretty representation of this subtitle file."""

        click.secho('Subtitle File: {}'.format(self.file_name), fg='magenta')
        click.echo('  Encoding: {}'.format(self.encoding))
