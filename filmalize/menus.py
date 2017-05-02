"""CLI menu functions for filmalize.

This module contains the functions that define the menu system that the user
uses to select the streams to transcode and/or edit transcoding parameters.

"""

import sys
import os
from pathlib import PurePath

import click

import filmalize.defaults as defaults
from filmalize.errors import UserCancelError


class SelectedStreams(click.ParamType):
    """Custom Click parameter type to validate a selection of streams from a
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
        """Validate that input stream indexes are acceptable. Return indexes
        formatted as a list of integers."""

        try:
            selected = [int(index) for index in value.strip().split(' ')]
        except (ValueError, TypeError):
            self.fail('Invalid input. Enter stream indexes separated by a '
                      'single space')

        try:
            if self.container.acceptable_streams(selected):
                return selected
        except ValueError as _e:
            self.fail(_e)


def main_menu(containers):
    """The main menu, which is loaded when running the convert command.

    The main menu is presented for each container given, preceeded by a pretty
    representation of the container and a description of the actions to be
    taken. The user may select from the options Convert, Skip, Edit, and Quit.
    If convert is selected, the conversion is started immediately in a
    subprocess. However, those processes will be terminated if Quit is
    subsequently selected. If the user selects Edit, the edit menu is loaded.

    Args:
        containers (:obj:`list` of :obj:`Container`): Candidates for
            conversion.

    Returns:
        :obj:`list` of :obj:`Container`: The instances that were approved by
        the user and started.

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

    The user may elect to edit the :obj:`Stream` or :obj:`SubtitleFile`
    instances associated with the given :obj:`Container`, change the ouput
    filename, display the raw ffmpeg command, or return to the main menu.

    Args:
        container (:obj:`Container`): The Container instance to edit.

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

    The user may elect to select the :obj:`Stream` instances to be included in
    the output file or edit the parameters of one of those streams.

    Args:
        container (:obj:`Container`): The Container object whose :obj:`Stream`
        instances to select from or edit.

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
    :obj:`SubtitleFile`.

    Args:
        container (:obj:`Container`): The Container instance whose SubtitleFile
           instances to add to, remove, or change.

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


def yes_no(prompt):
    """Utility function to ask the user a yes/no question.

    Note:
        The user must enter 'y' or 'n', and will be prompted repeatedly until
        they do so.

    Args:
        prompt (:obj:`str`): The question to ask the user.

    Returns:
        :obj:`bool`: True if the user enters 'y' or False if the user enters
        'n'.

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
        prompt (:obj:`str`): The question to ask the user.
        responses (:obj:`list` of :obj:`str`): The possible answers to the
            question in the form of individual characters. The characters will
            be displayed to the user separated by '/' characters.
        key (:obj:`str`, optional): A key to relate the characters in the
            responses list to answers to the prompt.

    Returns:
        :obj:`str`: The character from the responses list that the user
        selected.

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
    """Echo a pretty representation of a given :obj:`Container` instance."""

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
    """Echo a pretty representation of the conversion actions to perform on a
    given :obj:`Container`."""

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
    """Echo a pretty representation of a given :obj:`Stream`."""

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
    """Echo a pretty representation of a given :obj:`SubtitleFile`."""

    click.secho('Subtitle File: {}'.format(sub_file.file_name), fg='magenta')
    click.echo('  Encoding: {}'.format(sub_file.encoding))


def display_command(container):
    """Echo the current compiled command for a given :obj:`Container`."""

    click.secho('Command:', fg='cyan', bold=True)
    click.echo(' '.join(container.build_command()))


def add_subtitles(container):
    """Prompt the user to add an external subtitle file (:obj:`SubtitleFile`)
    to a given :obj:`Container`.

    Raises:
        :obj:`UserCancelError`: If the user cancels adding a subtitle file.

    """

    try:
        sub_file = click.prompt('Enter subtitle file name', type=click.Path(
            exists=True, dir_okay=False, readable=True))
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled adding subtitle file.')

    container.add_subtitle_file(sub_file)


def remove_subtitles(container):
    """Prompt the user to remove a chosen :obj:`SubtitleFile` instance from a
    given :obj:`Container`.

    Raises:
        :obj:`UserCancelError`: If the user cancels removing a subtitle file,
            or if there are no subtitle files to remove.

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
    """Promt the user to set a custom encoding for a :obj:`SubtitleFile` in a
    given:obj:`Container`.

    Raises:
        :obj:`UserCancelError`: If there are no subtitle files to change or the
            user cancels changing a subtitle file.

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
    """Prompt the user to select the :obj:`Stream` instances of a given
    :obj:`Container` to include in the output file.

    Raises:
        :obj:`UserCancelError`: If the user cancels selecting streams.

    """

    try:
        display_container(container)
        container.selected = click.prompt('Which streams would you like',
                                          type=SelectedStreams(container))
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled selecting streams.')


def edit_stream_options(container):
    """Prompt the user to select a :obj:`Stream` instance from a given
    :obj:`Container` and edit its conversion options.

    Raises:
        :obj:`UserCancelError`: If the user cancels editing a stream.

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
            elif yes_no('Use default crf ({})?'.format(defaults.CRF)):
                stream.custom_crf = defaults.CRF
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
                        .format(defaults.BITRATE)):
                stream.custom_bitrate = defaults.BITRATE
            else:
                stream.custom_bitrate = click.prompt(
                    'Enter bitrate', type=click.IntRange(0, 5000)
                )
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled editing stream.')


def change_file_name(container):
    """Prompt the user to specify a name for the output file produced by a
    given :obj:`Container` instance.

    Raises:
        :obj:`UserCancelError`: If the user cancels entering a name.

    """

    default = PurePath(container.file_name).stem + defaults.ENDING
    try:
        if yes_no('Use default file name ({})?'.format(default)):
            container.output_name = default
        else:
            name = click.prompt('Enter output file name (without extension)')
            container.output_name = name + defaults.ENDING
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled editing file name.')
