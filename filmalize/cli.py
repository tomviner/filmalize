"""Command-Line Interface for filmalize."""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePath

import click
import progressbar
import blessed

from filmalize.errors import (ProbeError, UserCancelError, NoProgressError,
                              ProgressFinishedError)
from filmalize.models import Container

DEFAULT_BITRATE = 384
DEFAULT_CRF = 18
# Allow help to be called with '-h' as well as the default '--help'.
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


class SelectedStreams(click.ParamType):
    """Custom Click parameter type to validate a selection of streams from a
    Container."""

    def __init__(self, container):
        """Initialize type: Set working Container."""

        self.container = container

    def convert(self, value, param, ctx):
        """Validate that input stream indices are acceptable. Return indices
        formatted as a list of integers."""

        try:
            selected = [int(index) for index in value.strip().split(' ')]
        except (ValueError, TypeError):
            self.fail('Invalid input. Enter stream indexes separated by a '
                      'single space')

        try:
            self.container.acceptable_streams(selected)
        except ValueError as _e:
            self.fail(_e)

        else:
            return selected


class Writer(object):
    """An object to write to method that writes to a specific line on the
    screen, defined at instantiation. This is to be used as a file descriptor
    for a progresbar.ProgressBar object."""

    def __init__(self, line, terminal, color=None):
        """Populate instance variables.

        Note:
            The optional color argument must conform to the Blessed color
            attribute format as it will be called.

        Args:
            line (int): The line of the screen for this instance to write to.
            terminal (blessed.Terminal): The Terminal object with which to
                write.
            color (str, optional): The color to print in.

        """

        self.line = line
        self.terminal = terminal
        self.color = color

    def write(self, message):
        """Write a message to the screen.

        The message is written to the blessed.Terminal object stored in
        self.terminal, and in self.color, if set.

        Args:
            message (str): The message to display

        """
        with self.terminal.location(x=0, y=self.line):
            if self.color:
                print(getattr(self.terminal, self.color)(message))
            else:
                print(message)

    @staticmethod
    def flush():
        """progresbar.ProgressBar objects expect to flush their file
        descriptors, but we don't need to worry about that."""
        return True


class ErrorWriter(object):
    """Writes messages in bright red to the bottom of a Terminal."""

    def __init__(self, terminal):
        """Populate instance variables.

        Args:
            terminal (blessed.Terminal): The Terminal object to write to.

        """

        self.terminal = terminal
        self.line = terminal.height
        self.messages = []

    def write(self, message):
        """Write a message to the next lowest line on the Terminal.

        Next, decrement self.line so that the following message goes in the
        right place. Finally, add message to self.messages for safekeeping.

        Args:
            message (str): The message to display.

        """

        with self.terminal.location(x=0, y=self.line):
            print(self.terminal.red(message))
        self.line -= 1
        self.messages.append(message)


def exclusive(ctx_params, exclusive_params, error_message):
    """Utility function for enforcing exclusivity between options.

    Call at the top of a click.group() or click.group.command() function.

    Args:
        ctx_params (dict): The context parameters to search.
        exclusive_params (list of strings): Mutually exclusive parameters.
        error_message (str): The error message to display.

    Raises:
        click.UsageError: If more than one exclusive parameter is present in
            the context parameters.

    Examples:
        exclusive(click.get_current_context().params, ['param1', 'param2'],
            'paramters param1 and param2 are mutually exclusive')

        exclusive({**ctx.params, **ctx.parent.params}, ['a', 'b'],
            'command option b may not be specified with application option a')

    """

    if sum([1 if ctx_params[p] else 0 for p in exclusive_params]) > 1:
        raise click.UsageError(error_message)


def yes_no(prompt):
    """Utility function to ask the user a yes/no question.

    Note:
        The user must enter 'y' or 'n', and will be prompted repeatedly until
        they do so.

    Args:
        prompt (str): The question to ask the user.

    Returns:
        bool: True if the user enters 'y' or false if the user enters 'n'.

    """
    while True:
        click.echo(prompt + ' [y/n]', nl=False)
        char = click.getchar()
        click.echo()
        if char == 'y':
            return True
        elif char == 'n':
            return False
        else:
            click.echo('Invalid input, try again...')


def multiple_choice(prompt, responses, key=None):
    """Utility function to ask the user a multple choice question.

    Note:
        The user must enter one of the characters in the responses list, and
        will be prompted repeatedly until they do so.

    Args:
        prompt (str): The question to ask the user.
        responses (list of str): The possible answers to the question in the
            form of individual characters. The characters will be displayed to
            the user separated by '/' characters.
        key (str, optional): A key to relate the characters in the responses
            list to answers to the prompt.

    Returns:
        str: The character from the responses list that the user selected.

    """

    while True:
        click.echo()
        options = ' ' + '/'.join(responses)
        click.echo(click.style('*** ' + prompt, fg='blue', bg='white',
                               bold=True) + options)
        if key:
            click.echo(click.style('Key: ', fg='red') + key)
        char = click.getchar()
        click.echo()
        if char in responses:
            return char
        else:
            click.echo('Invalid input, try again...')


def display_container(container):
    """Echo a pretty representation of a given Container."""

    click.secho('*** File: {} ***'.format(container.file_name), fg='magenta')
    if container.labels.title:
        click.secho('Title: {}'.format(container.labels.title), fg='cyan')

    file_description = ['Length: {}'.format(container.length)]
    file_description.append('Size: {}MiB'.format(container.labels.size))
    file_description.append('Bitrate: {}Mib/s'
                            .format(container.labels.bitrate))
    file_description.append('Container: {}'
                            .format(container.labels.container_format))
    click.echo(' | '.join(file_description))

    for stream in container.streams:
        display_stream(stream)

    for sub_file in container.subtitle_files:
        display_sub_file(sub_file)


def display_conversion(container):
    """Echo a pretty representation of the conversion actions to take.

    Args:
        container (Container): The Container to display.

    """

    click.clear()
    display_container(container)
    click.secho('Filmalize Actions:', fg='cyan', bold=True)
    for stream in container.streams:
        if stream.index in container.selected:
            header = 'Stream {}: '.format(stream.index)
            stream.build_options()
            info = stream.option_summary
            click.echo(click.style(header, fg='green', bold=True)
                       + click.style(info, fg='yellow'))
    for subtitle in container.subtitle_files:
        click.echo(
            click.style(subtitle.file_name + ': ', fg='green', bold=True)
            + click.style(subtitle.option_summary, fg='yellow')
        )
    click.secho('Output File: {}'.format(container.output_name), fg='magenta')


def display_stream(stream):
    """Echo a pretty representation of a given Stream."""

    stream_header = 'Stream {}:'.format(stream.index)
    stream_info = [stream.type, stream.codec]
    stream_info.append(stream.labels.language)
    stream_info.append(stream.labels.default)
    click.echo('  ' + click.style(stream_header, fg='green', bold=True)
               + ' ' + click.style(' '.join(stream_info), fg='yellow'))

    if stream.labels.title:
        click.echo('    Title: {}'.format(stream.labels.title))

    stream_specs = []
    if stream.type == 'video':
        stream_specs.append('Resolution: {}'
                            .format(stream.labels.resolution))
        stream_specs.append('Bitrate: {}Mib/s'.format(stream.labels.bitrate))
    elif stream.type == 'audio':
        stream_specs.append('Channels: {}'.format(stream.labels.channels))
        stream_specs.append('Bitrate: {}Kib/s'.format(stream.labels.bitrate))
    if stream_specs:
        click.echo('    ' + ' | '.join(stream_specs))


def display_sub_file(sub_file):
    """Echo a pretty representation of a given SubtitleFile."""

    click.secho('Subtitle File: {}'.format(sub_file.file_name), fg='magenta')
    click.echo('  Encoding: {}'.format(sub_file.encoding))


def display_command(container):
    """Echo the current compiled command for a given Container."""

    click.secho('Command:', fg='cyan', bold=True)
    click.echo(' '.join(container.build_command()))


def add_subtitles(container):
    """Add an external subtitle file to a given container.

    Args:
        container (Container): The Container to add a subtitle file to.

    Raises:
        UserCancelError: If the user cancels adding a subtitle file.

    """

    try:
        sub_file = click.prompt('Enter subtitle file name', type=click.Path(
            exists=True, dir_okay=False, readable=True))
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled adding subtitle file.')

    container.add_subtitle_file(sub_file)


def remove_subtitles(container):
    """Remove an external subtitle file.

    Args:
        container (Container): The Container to remove the subtitle file from.

    Raises:
        UserCancelError: If the user cancels removing a subtitle file, or if
        there are no subtitle files to remove.

    """

    if not container.subtitle_files:
        raise UserCancelError('There are no subtitle files to remove.')
    else:
        for index, subtitle in enumerate(container.subtitle_files):
            click.secho('Number: {}'.format(index), fg='cyan', bold=True)
            display_sub_file(subtitle)
        file_indices = [str(i) for i in range(len(container.subtitle_files))]
        acceptable = file_indices + ['c']
        action = multiple_choice('Enter the file number to remove, or c to '
                                 'cancel:', acceptable)
        if action == 'c':
            raise UserCancelError('Cancelled subtitle file removal.')
        else:
            container.subtitle_files.pop(int(action))


def change_subtitle_encoding(container):
    """Set a custom encoding for a SubtitleFile in a given Container.

    Args:
        container (Container): The Container containing the subtitle file to be
            change.

    Raises:
        UserCancelError: If there are no subtitle files to change or the user
            cancels changing a subtitle file.

    """

    if not container.subtitle_files:
        raise UserCancelError('There are no subtitle files to remove.')
    else:
        for index, subtitle in enumerate(container.subtitle_files):
            click.secho('Number: {}'.format(index), fg='cyan', bold=True)
            display_sub_file(subtitle)
        file_indices = [str(i) for i in range(len(container.subtitle_files))]
        acceptable = file_indices + ['c']
        action = multiple_choice('Enter the file number to change, or c to '
                                 'cancel:', acceptable)
        if action == 'c':
            raise UserCancelError('Cancelled subtitle file removal.')
        else:
            try:
                encoding = click.prompt('Enter custom encoding')
            except click.exceptions.Abort:
                raise UserCancelError('Cancelled changing encoding.')
            container.subtitle_files[int(action)].encoding = encoding


def select_streams(container):
    """Prompt the user to select streams for processing.

    Args:
        container (Container): The Container from which the user will select
            Streams.

    Raises:
        UserCancelError: If the user cancels selecting streams.

    """

    try:
        display_container(container)
        query = 'Which streams would you like'
        streams = click.prompt(query, type=SelectedStreams(container))
        container.selected = streams
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled selecting streams.')


def edit_stream_options(container):
    """Prompt the user to select a stream. Edit that stream's options.

    Args:
        container (Container): The Container with streams to be edited

    Raises:
        UserCancelError: If the user cancels editing a stream.

    """

    display_container(container)
    indexes = [str(stream.index) for stream in container.streams
               if (stream.type in ['audio', 'video']
                   and stream.index in container.selected)]

    try:
        stream = container.streams_dict[
            int(multiple_choice('Select a stream:', indexes))
        ]
        if stream.type == 'video':
            if stream.codec == 'h264' and yes_no('Copy stream?'):
                stream.custom_crf = None
            elif yes_no('Use default crf ({})?'.format(DEFAULT_CRF)):
                stream.custom_crf = DEFAULT_CRF
            else:
                crf = click.prompt('Enter crf', type=click.IntRange(0, 51))
                stream.custom_crf = crf
        elif stream.type == 'audio':
            if stream.codec == 'aac' and yes_no('Copy stream?'):
                stream.custom_bitrate = None
            elif stream.labels.bitrate and yes_no(
                    'Use source bitrate ({}Kib/s)?'
                    .format(stream.labels.bitrate)
            ):
                stream.custom_bitrate = stream.labels.bitrate
            elif yes_no('Use default bitrate ({}Kib/s)?'
                        .format(DEFAULT_BITRATE)):
                stream.custom_bitrate = DEFAULT_BITRATE
            else:
                stream.custom_bitrate = click.prompt(
                    'Enter bitrate', type=click.IntRange(0, 5000)
                )
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled editing stream.')


def change_file_name(container):
    """Prompt the user to specify a name for the output file.

    Args:
        container (Container): The Container whose filename to change.

    Raises:
        UserCancelError: If the user cancels entering a name.

    """

    default = PurePath(container.file_name).stem + '.mp4'
    try:
        if yes_no('Use default file name ({})?'.format(default)):
            container.output_name = default
        else:
            name = click.prompt('Enter output file name (without extension)')
            container.output_name = name + '.mp4'
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled editing file name.')


def build_containers(file_list):
    """Utility function to build a list of Container objets given a list of
        filenames.

    Note:
        If a container fails to build as the result of a ffprobe error, that
            error is echoed, and the building continues. If no containers are
            built, return an empty list.

    Args:
        file_list (list): File names (str) to attempt to build into containers.

    Returns:
        list: Succesfully built containers.

    """

    containers = []
    with ThreadPoolExecutor() as executor:
        futures = []
        for file_name in file_list:
            futures.append(executor.submit(Container.from_file, file_name))
        for future in as_completed(futures):
            try:
                containers.append(future.result())
            except ProbeError as _e:
                click.secho('Warning: unable to process {}'
                            .format(_e.file_name), fg='red')
                click.echo(_e.message)
    return sorted(containers, key=lambda container: container.file_name)


def main_menu(containers):
    """The main menu, which is loaded when running the convert command.

    The main menu is presented for each container given, preceeded by a pretty
    representation of the container and a description of the actions to be
    taken. The user may select from the options Convert, Skip, Edit, and Quit.
    If convert is selected, the conversion is started immediately in a
    subprocess. However, those processes will be terminated if Quit is
    subsequently selected.

    Args:
        containers (list): The Container objects to convert.

    Returns:
        list: The container objects whose convert processes have been started.

    """

    running = []
    for container in containers:
        menu = 'main'
        while True:
            if menu == 'main':
                display_conversion(container)

                menu = multiple_choice('Main Menu:', ['c', 's', 'e', 'q'],
                                       'Convert/Skip/Edit/Quit')
            elif menu == 'c':
                container.convert()
                running.append(container)
                break
            elif menu == 's':
                break
            elif menu == 'e':
                edit_menu(container)
                menu = 'main'
            elif menu == 'q':
                for running_container in running:
                    running_container.process.terminate()
                sys.exit('Conversion cancelled.')

    return running


def edit_menu(container):
    """The edit menu, which is accessible from the main menu.

    The user may elect to edit the Streams or SubtitleFiles associated with the
    given container, change the ouput filename, display the raw ffmpeg command,
    or return to the main menu.

    Args:
        container (Container): The Container object to edit.

    """
    menu = 'edit'
    while True:
        if menu == 'edit':
            menu = multiple_choice('Edit Menu:', ['e', 's', 'f', 'd', 'm'],
                                   'Edit Streams/Subtitle Files/'
                                   'Change Filename/Display Command/Main Menu')
        elif menu == 'm':
            break
        else:
            options = {'e': stream_menu, 's': subtitle_menu,
                       'f': change_file_name, 'd': display_command}
            try:
                options[menu](container)
            except UserCancelError as _e:
                click.secho('{}Warning: {}'.format(os.linesep, _e.message),
                            fg='red')
            menu = 'edit'


def stream_menu(container):
    """The stream menu, which is accessible from the edit menu.

    The user may elect to select the streams to be used in the output file or
    edit the parameters of one of those streams.

    Args:
        container (Container): The Container object whose Stream objects to
        select from or edit.

    """

    display_conversion(container)
    menu = multiple_choice('Stream Menu:', ['s', 'e', 'c'],
                           'Select Active Streams/Edit Stream/Cancel')
    if menu == 'c':
        return
    else:
        options = {'s': select_streams, 'e': edit_stream_options}
        options[menu](container)


def subtitle_menu(container):
    """The subtitle menu, which is accessible from the edit menu.

    The user may elect to add, remove, or change the encoding of a
    SubtitleFile.

    Args:
        container (Container): The Container object whose SubtitleFile objects
        to add, remove, or change.

    """

    display_conversion(container)
    menu = multiple_choice('Subtitle File Menu:', ['a', 'r', 'e'],
                           'Add/Remove/Change Encoding')
    if menu == 'c':
        return
    else:
        options = {'a': add_subtitles, 'r': remove_subtitles,
                   'e': change_subtitle_encoding}
        options[menu](container)


def get_progress(container):
    """Get the transcoding progress of a given Container in microseconds.

    Args:
        container (Container): The Container whose transcoding process to
            check.

    Returns:
        int: The number of microseconds of the file that ffmpeg has finished
            transcoding.

    Raises:
        ProgressFinishedError: If the subprocess is not running (either
            finished or errored out).
        NoProgressError: If unable to read the progress from the temp_file.


    """

    if container.process.poll() is not None:
        raise ProgressFinishedError
    else:
        with open(container.temp_file.name, 'r') as status:
            line_list = status.readlines()
        microsec = 0
        for line in reversed(line_list):
            if line.split('=')[0] == 'out_time_ms':
                try:
                    microsec = int(line.split('=')[1])
                    break
                except (ValueError, TypeError):
                    raise NoProgressError

        pre_progress = container.progress
        container.progress = microsec
        return microsec - pre_progress


def build_progress_bars(running, terminal):
    """Create ProgressBar objects for each Container in the given list as well
    as one for all of them.

    The ProgressBar objects are added to each Container as pr_bar.

    Args:
        running (list): The Container objects to create ProgressBar objects
            for.
        terminal (blessed.Terminal): The object to attach each ProgressBar
            object to.

    Returns:
        progresbar.ProgressBar: An object for tracking the progress of all of
            the passed Containers.

    """

    padding = max([len(container.file_name) for container in running])
    for line_number, container in enumerate(running):
        label = '{n:{l}}'.format(n=container.file_name, l=padding)
        widgets = [label, ' | ', progressbar.Percentage(), ' ',
                   progressbar.Bar(), ' ', ' | ', progressbar.ETA()]
        writer = Writer(line_number + 2, terminal, 'red_on_black')
        container.pr_bar = progressbar.ProgressBar(
            max_value=container.microseconds, widgets=widgets, fd=writer)

    writer = Writer(0, terminal, 'bold_blue_on_black')
    total_ms = sum([container.microseconds for container in running])
    label = 'Processing {} files:'.format(len(running))
    widgets = [label, ' | ', progressbar.Percentage(), ' ', progressbar.Bar(),
               ' ', progressbar.Timer(), ' | ', progressbar.ETA()]

    return progressbar.ProgressBar(max_value=total_ms, widgets=widgets,
                                   fd=writer)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '-f', '--file', help='Specify a file.',
    type=click.Path(exists=True, dir_okay=False, readable=True),
)
@click.option(
    '-d', '--directory', help='Specify a directory.',
    type=click.Path(exists=True, file_okay=False, readable=True)
)
@click.option('-r', '--recursive', is_flag=True, help='Operate recursively.')
@click.pass_context
def cli(ctx, file, directory, recursive):
    """A simple tool for converting video files.

    By default filmalize operates on all files in the current directory. If
    desired, you may specify an individual file or a different working
    directory. Directory operation may be recursive. A command is required.

    """

    exclusive(ctx.params, ['file', 'directory'],
              'a file may not be specified with a directory')
    exclusive(ctx.params, ['file', 'recursive'],
              'a file may not be specified with the recursive flag')

    ctx.obj = {}

    if file:
        ctx.obj['FILES'] = [file]
    else:
        directory = directory if directory else '.'
        if recursive:
            ctx.obj['FILES'] = sorted(
                [os.path.join(root, file)
                 for root, dirs, files in os.walk(directory)
                 for file in files]
            )
        else:
            ctx.obj['FILES'] = sorted(
                [dir_entry.path for dir_entry in os.scandir(directory)
                 if dir_entry.is_file()]
            )


@cli.command()
@click.pass_context
def display(ctx):
    """Display information about video file(s)"""

    for container in build_containers(ctx.obj['FILES']):
        display_container(container)


@cli.command()
@click.pass_context
def convert(ctx):
    """Convert video file(s)"""

    containers = build_containers(ctx.obj['FILES'])
    running = main_menu(containers)
    terminal = blessed.Terminal()
    pr_bar = build_progress_bars(running, terminal)
    err = ErrorWriter(terminal)

    with terminal.fullscreen():
        while running:
            for container in running:
                try:
                    progress = get_progress(container)
                    container.pr_bar.update(container.pr_bar.value + progress)
                except (ProgressFinishedError, NoProgressError) as _e:
                    if container.process.returncode:
                        err.write('Warning: ffmpeg error while converting'
                                  '{}'.format(container.file_name))
                        err.write(container.process.communicate()[1]
                                  .strip(os.linesep))
                    if isinstance(_e, NoProgressError):
                        err.write('Warning: Unable to track progress of {}'
                                  .format(container.file_name))

                    running.remove(container)
                    progress = (container.microseconds - container.progress)
                    container.pr_bar.finish()

                pr_bar.update(pr_bar.value + progress)

            time.sleep(0.2)

    pr_bar.finish()
    for message in err.messages:
        click.secho(message, fg='red', bg='black', )


if __name__ == '__main__':
    cli()
