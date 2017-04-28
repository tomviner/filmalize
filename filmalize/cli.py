"""Command-Line Interface for filmalize."""

import os
import time
from pathlib import PurePath
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
import chardet

from filmalize.errors import ProbeError, UserCancelError
from filmalize.models import Container, SubtitleFile

DEFAULT_BITRATE = 384
DEFAULT_CRF = 18


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
        if key:
            click.echo('Key: {}'.format(key))
        full_prompt = prompt + ' [{}]'.format('/'.join(responses))
        click.echo(full_prompt, nl=False)
        char = click.getchar()
        click.echo()
        if char in responses:
            return char
        else:
            click.echo('Invalid input, try again...')


def display_container(container):
    """Echo a pretty representation of a Container."""

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
    """Echo a pretty representation of the stream.

    Args:
        stream (Stream): The Stream to display.

    """

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
    """Echo a pretty representation of the subtitle file.

    Args:
        sub_file (SubtitleFile): The SubtitleFile to display.

    """

    click.secho('Subtitle File: {}'.format(sub_file.file_name), fg='magenta')
    click.echo('  Encoding: {}'.format(sub_file.encoding))


def add_subtitles(container):
    """Add an external subtitle file. Allow the user to set a custom encoding.

    Args:
        container (Container): The Container to add the subtitle file to.

    Raises:
        UserCancelError: If the user cancels adding a subtitle file.

    """

    sub_file, encoding = sub_file_prompt()
    while True:
        char = multiple_choice('Continue?', ['a', 'r', 's', 'c'],
                               'accept / retry / specify custom / cancel')
        if char == 'a':
            if not encoding:
                click.secho('Warning: No encoding specified. '
                            'Retry or specify one.', fg='red')
            else:
                container.subtitle_files.append(
                    SubtitleFile(sub_file, encoding))
                break
        elif char == 'r':
            sub_file, encoding = sub_file_prompt()
        elif char == 's':
            encoding = click.prompt('Enter custom encoding')
            click.echo('Custom encoding specified: {}'.format(encoding))
        elif char == 'c':
            raise UserCancelError('Cancelled subtitle file addition.')


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


def sub_file_prompt():
    """Prompt the user to specify a subtitle file.

    Use chardet to detect the character encoding. Display the detected
    encoding and confidence to the user.

    Returns:
        string: The subtitle file name
        string: The subtitle file encoding

    """
    try:
        sub_file = click.prompt('Enter subtitle file name', type=click.Path(
            exists=True, dir_okay=False, readable=True))
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled adding subtitle file.')

    with open(sub_file, mode='rb') as _file:
        line = _file.readline()
    detected = chardet.detect(line)
    click.echo(
        'Subtitle file encoding detected as {}, with {}% confidence'.format(
            detected['encoding'], int(detected['confidence']) * 100)
    )
    return sub_file, detected['encoding']


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
            elif yes_no('Use default crf?'):
                stream.custom_crf = DEFAULT_CRF
            else:
                crf = click.prompt('Enter crf', type=click.IntRange(0, 51))
                stream.custom_crf = crf
        elif stream.type == 'audio':
            if stream.codec == 'aac' and yes_no('Copy stream?'):
                stream.custom_bitrate = None
            elif stream.bitrate and yes_no(
                    'Use source bitrate ({}Kib/s)?'
                    .format(stream.bitrate)
            ):
                stream.custom_bitrate = stream.bitrate
            elif yes_no('Use default bitrate (384Kib/s)?'):
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


@click.group()
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
    running = []
    for container in containers:
        while True:
            display_container(container)
            display_conversion(container)
            char = multiple_choice(
                'Convert file?', ['y', 'n', 'a', 'r', 's', 'e', 'c', 'd'],
                ('yes/no/{add,remove} subtitle file/{select,edit} streams/'
                 'change filename/display command')
            )
            try:
                if char == 'n':
                    raise UserCancelError('Cancelled converting {}'
                                          .format(container.file_name))
                elif char == 'a':
                    add_subtitles(container)
                elif char == 'r':
                    remove_subtitles(container)
                elif char == 's':
                    select_streams(container)
                elif char == 'e':
                    edit_stream_options(container)
                elif char == 'c':
                    change_file_name(container)
                elif char == 'd':
                    click.secho('Command:', fg='cyan', bold=True)
                    click.echo(' '.join(container.build_command()))
            except UserCancelError as _e:
                click.secho('{}Warning: {}'.format(os.linesep, _e.message),
                            fg='red')
            if char == 'y':
                container.convert()
                running.append(container)
            if char in ['y', 'n']:
                break

    total_ms = sum([container.microseconds for container in running])
    label = 'Processing {} files:'.format(len(running))
    with click.progressbar(length=total_ms, label=label) as pr_bar:
        while running:
            for container in running:
                if container.process.poll() is not None:
                    if container.process.returncode:
                        click.secho('Warning: ffmpeg error while converting'
                                    '{}'.format(container.file_name),
                                    fg='red')
                        click.echo(container.process.communicate()[1]
                                   .strip(os.linesep))
                    pr_bar.update(container.microseconds - container.progress)
                    running.remove(container)
                else:
                    with open(container.temp_file.name, 'r') as status:
                        line_list = status.readlines()
                    microsec = 0
                    for line in reversed(line_list):
                        if line.split('=')[0] == 'out_time_ms':
                            if line.split('=')[1].strip(os.linesep).isdigit():
                                microsec = int(line.split('=')[1])
                                break
                    if microsec:
                        pr_bar.update(microsec - container.progress)
                        container.progress = microsec
            time.sleep(1)


if __name__ == '__main__':
    cli()
