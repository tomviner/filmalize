"""A simple tool for converting video files.

System Dependencies:
    * ffmpeg
    * python 3.4

Todo:
    * Config file
    * Filename whitelist?
    * Tests
    * Status interrupts
    * Specify metadata edits
    * TVDB API?
    * Install / packaging

"""

import os
import subprocess
import json
import datetime
import tempfile
import time
import pathlib

import click
import bitmath
import chardet


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


class SelectedStreams(click.ParamType):
    """Custom Click parameter type to validate a selection of streams from a
    Container."""

    def __init__(self, container):
        """Initialize type: get streams from container."""

        self.streams = container.streams

    def convert(self, value, param, ctx):
        """Validate that input stream indices are acceptable. Return indices
        formatted as a list of integers."""

        selected = value.strip().split(' ')
        video, audio = False, False
        for selection in selected:
            if not selection.isdigit():
                self.fail('Invalid input. Enter stream indices separated by a '
                          'single space.')
            stream = int(selection)
            if stream not in self.streams.keys():
                self.fail('Invalid input. {} is not an available stream '
                          'index.'.format(stream))
            elif self.streams[stream].type == 'audio':
                audio = True
            elif self.streams[stream].type == 'video':
                video = True
        if audio and video:
            return [int(s) for s in selected]
        else:
            self.fail('Invalid input. You must include at least one audio and '
                      'one video stream.')


class Container(object):
    """Multimedia container file object."""

    def __init__(self, file_name, duration, streams, subtitle_files=None,
                 title=None, size=None, bitrate=None, container_format=None):
        """Populate container object instance variables.

        Args:
            file_name (str): The multimedia container file to represent.
            duration (float): The duration of the streams in the container in
                seconds.
            streams (dict): A dictionary containing Stream objects as values
                keyed by their index values.
            subtitle_files (list): Optional list of SubtitleFile objects.
            title (str): Optional container title label.
            size (float): Optional container size label in MiBs.
            bitrate (float): Optional container bitrate label in Mib/s.
            container_format (str): Optional container format label. Regardless
                of the presence of this label, the container must be a format
                that ffmpeg can process.

        """

        self.file_name = file_name
        self.duration = duration
        self.streams = streams
        self.subtitle_files = subtitle_files if subtitle_files else []
        self.title = title
        self.size = size
        self.bitrate = bitrate
        self.container_format = container_format

        self.microseconds = int(duration * 1000000)
        self.length = datetime.timedelta(seconds=round(duration, 0))

    def add_subtitle_file(self, file_name, encoding):
        """Add an external subtitle file. Allow the user to set a custom
        encoding.

        Args:
            file_name (str): The name of the subtitle file.
            encoding (str): The encoding of the subtitle file.

        """

        index = len(self.subtitle_files + 1)
        self.subtitle_files[index] = SubtitleFile(file_name, encoding)

    def display(self):
        """Echo a pretty representation of the Container."""

        if self.title:
            click.secho('Title: {}'.format(self.title), fg='cyan')
        click.secho('File: {}'.format(self.file_name), fg='magenta')

        file_description = []
        if self.length:
            file_description.append('Length: {}'.format(self.length))
        if self.size:
            file_description.append('Size: {}MiB'.format(self.size))
        if self.bitrate:
            file_description.append('Bitrate: {}Mib/s'.format(self.bitrate))
        if self.container_format:
            file_description.append('Container: {}'.format(
                self.container_format))
        click.echo(' | '.join(file_description))

        for _, stream in self.streams.items():
            stream.display()

        for subtitle in self.subtitle_files:
            subtitle.display()


class Stream(object):
    """Multimedia stream object."""

    def __init__(self, index, stream_type, codec, language=None, default=None,
                 title=None, resolution=None, bitrate=None, scan=None,
                 channels=None, crf=None, custom_bitrate=None):
        """Populate Stream object instance variables.

        Args:
            index (int): The stream index.
            stream_type (str): The multimedia type of the stream. Streams will
                be included only if they are of type 'audio', 'video', or
                'subtitle'.
            codec (str): The codec with which the stream is encoded. Must be a
                codec that ffmpeg will recognize.
            language (str): Optional language name or abbr.
            default (bool): Optional indication of this stream being the
                default of it's type.
            title (str): Optional stream title label.
            resolution (str): Optional stream resolution label.
            bitrate (float): Optional (video) stream bitrate in Mib/s.
            bitrate (int): Optional (audio) stream bitrate in Kib/s.
            scan (str): Optional (video) stream scanning information
                (progressive scan or interlaced).
            channels (str): Optional (audio) channel information (stereo, 5.1,
                etc.).
            crf (int): Optional (video) stream Constant Rate Factor.
            custom_bitrate (int): Optional (audio) stream output bitrate to
                transcode to.

        """

        self.index = index
        self.type = stream_type
        self.codec = codec
        self.language = language
        self.default = default
        self.title = title
        self.resolution = resolution
        self.bitrate = bitrate
        self.scan = scan
        self.channels = channels
        self.crf = crf
        self.custom_bitrate = custom_bitrate
        self.option_summary = None

    def build_options(self, number=0):
        """Generate ffmpeg codec/bitrate options for this Stream.

        The options generated will use custom values for video CRF or audio
        bitrate, if specified, or the default values. The option_summary is
        updated to reflect the selected options.

        Args:
            number (int): The number of Streams of this type that have been
            added to the command.

        Returns:
            list: The ffmpeg options for this Stream.

        """

        options = []
        if self.type == 'video':
            options.extend(['-c:v:{}'.format(number)])
            if self.crf or self.codec != 'h264':
                crf = self.crf if self.crf else 18
                options.extend(['libx264', '-preset', 'slow', '-crf', str(crf),
                                '-pix_fmt', 'yuv420p'])
                self.option_summary = 'transcode -> h264, crf={}'.format(crf)
            else:
                options.extend(['copy'])
                self.option_summary = 'copy'
        elif self.type == 'audio':
            options.extend(['-c:a:{}'.format(number)])
            if self.custom_bitrate or self.codec != 'aac':
                if self.custom_bitrate:
                    bitrate = self.custom_bitrate
                else:
                    bitrate = self.bitrate if self.bitrate else 384
                options.extend(['aac', '-b:a:{}'.format(number),
                                '{}k'.format(bitrate)])
                self.option_summary = ('transcode -> aac, '
                                       'bitrate={}Kib/s').format(bitrate)
            else:
                options.extend(['copy'])
                self.option_summary = 'copy'
        elif self.type == 'subtitle':
            options.extend(['-c:s:{}'.format(number), 'mov_text'])
            self.option_summary = 'transcode -> mov_text'

        return options

    def display(self):
        """Echo a pretty representation of the stream."""

        stream_header = 'Stream {}:'.format(self.index)
        stream_info = []
        if self.type:
            stream_info.append(self.type)
        if self.codec:
            stream_info.append(self.codec)
        if self.language:
            stream_info.append(self.language)
        if self.default:
            stream_info.append('default')
        click.echo('  ' + click.style(stream_header, fg='green', bold=True)
                   + ' ' + click.style(' '.join(stream_info), fg='yellow'))

        if self.title:
            click.echo('    Title: {}'.format(self.title))

        stream_specs = []
        if self.type == 'video':
            if self.resolution:
                stream_specs.append('Resolution: {}'.format(self.resolution))
            if self.bitrate:
                stream_specs.append('Bitrate: {}Mib/s'.format(self.bitrate))
            if self.scan:
                stream_specs.append('Scan: {}'.format(self.scan))
        elif self.type == 'audio':
            if self.channels:
                stream_specs.append('Channels: {}'.format(self.channels))
            if self.bitrate:
                stream_specs.append('Bitrate: {}Kib/s'.format(self.bitrate))
        if stream_specs:
            click.echo('    ' + ' | '.join(stream_specs))


class SubtitleFile(object):
    """Subtitle file object."""

    def __init__(self, file_name, encoding):
        self.file_name = file_name
        self.encoding = encoding
        self.options = ['mov_text']
        self.option_summary = 'transcode -> mov_text'

    def display(self):
        """Echo a pretty representation of the subtitle file."""

        click.secho('Subtitle File: {}'.format(self.file_name), fg='magenta')
        click.echo('  Encoding: {}'.format(self.encoding))


class Processor(object):
    """Container processor object."""

    def __init__(self, container):
        """Initialize Processor object.

        Set up default values:
            Select the first audio and video stream.
            Use the same file name as the input file, but suffixed with '.mp4'.

        Args:
            container (Container): The container object to process.

        """

        self.container = container
        self.temp_file = tempfile.NamedTemporaryFile()
        self.streams = []
        self.process = None
        audio, video = None, None
        for index, stream in self.container.streams.items():
            if not audio and stream.type == 'audio':
                audio = True
                self.streams.append(index)
            elif not video and stream.type == 'video':
                video = True
                self.streams.append(index)
        output_stem = pathlib.PurePath(self.container.file_name).stem
        self.output_name = output_stem + '.mp4'
        self.progress = 0

    def execute(self):
        """Start processing the container."""

        self.process = subprocess.Popen(
            self.build_command(),
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

    def display(self):
        """Echo a pretty representation of the processing actions to take."""

        self.container.display()
        click.secho('Filmalize Actions:', fg='cyan', bold=True)
        for stream_num in self.streams:
            header = 'Stream {}: '.format(stream_num)
            stream = self.container.streams[stream_num]
            stream.build_options()
            info = stream.option_summary
            click.echo(click.style(header, fg='green', bold=True)
                       + click.style(info, fg='yellow'))
        for subtitle in self.container.subtitle_files:
            click.echo(
                click.style(subtitle.file_name + ': ', fg='green', bold=True)
                + click.style(subtitle.option_summary, fg='yellow')
            )
        click.secho('Output File: {}'.format(self.output_name), fg='magenta')

    def build_command(self):
        """Build the ffmpeg command to process this container.

        Generate appropriate ffmpeg options to process the selected streams.

        Returns:
            list: The ffmpeg command and options to execute.

        """

        command = ['/usr/bin/ffmpeg', '-nostdin', '-progress',
                   self.temp_file.name, '-v', 'error', '-y', '-i',
                   self.container.file_name]
        for subtitle in self.container.subtitle_files:
            command.extend(['-sub_charenc', subtitle.encoding, '-i',
                            subtitle.file_name])
        for stream in self.streams:
            command.extend(['-map', '0:{}'.format(stream)])
        for index, subtitle in enumerate(self.container.subtitle_files):
            command.extend(['-map', '{}:0'.format(index + 1)])
        stream_number = {'video': 0, 'audio': 0, 'subtitle': 0}
        output_streams = [self.container.streams[s] for s in self.streams]
        for stream in output_streams:
            command.extend(stream.build_options(stream_number[stream.type]))
            stream_number[stream.type] += 1
        for subtitle in self.container.subtitle_files:
            command.extend(['-c:s:{}'.format(stream_number['subtitle'])])
            command.extend(subtitle.options)
            stream_number['subtitle'] += 1
        command.extend([os.path.join(os.path.dirname(self.container.file_name),
                                     self.output_name)])
        return command


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
    """Utility function to ask the user a yes/no question."""

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
    """Utility function to ask the user a multple choice question."""

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


def build_stream(stream_info):
    """Build a Stream instance based on ffprobe stream information.

        Args:
            stream_info (dict): Stream information as reported by ffprobe.

        Returns:
            Stream: Instance populated by ffprobe stream information.

    """

    [language, default, title, resolution, bitrate, scan,
     channels] = [None for _ in range(7)]

    index = stream_info['index']
    stream_type = stream_info['codec_type']
    codec = stream_info['codec_name']

    if 'tags' in stream_info and 'language' in stream_info['tags']:
        language = stream_info['tags']['language']
    if ('disposition' in stream_info
            and 'default' in stream_info['disposition']):
        default = bool(stream_info['disposition']['default'])
    if 'tags' in stream_info and 'title' in stream_info['tags']:
        title = stream_info['tags']['title']

    if stream_type == 'video':
        if 'height' in stream_info and 'width' in stream_info:
            width = str(stream_info['width'])
            height = str(stream_info['height'])
            resolution = width + 'x' + height
        elif ('coded_height' in stream_info
              and 'coded_width' in stream_info):
            width = str(stream_info['coded_width'])
            height = str(stream_info['coded_height'])
            resolution = width + 'x' + height
        if 'bit_rate' in stream_info:
            bits = int(stream_info['bit_rate'])
            bitrate = round(bitmath.Mib(bits=bits).value, 2)
        if 'field_order' in stream_info:
            scan = stream_info['field_order']
    elif stream_type == 'audio':
        if 'channel_layout' in stream_info:
            channels = stream_info['channel_layout']
        if 'bit_rate' in stream_info:
            bits = int(stream_info['bit_rate'])
            bitrate = round(bitmath.Kib(bits=bits).value)

    return Stream(index, stream_type, codec, language=language,
                  default=default, title=title, resolution=resolution,
                  bitrate=bitrate, scan=scan, channels=channels)


def build_container(file_name):
    """Build a Container instance from a given file.

    Attempt to probe the file with ffprobe. If the probe is succesful, finish
    instatiation using the results of the probe, building Stream instances as
    necessary.

    Args:
        file_name (str): The file (a multimedia container) to represent.

    Returns:
        Container: Instance representing the given file.

    Raises:
        ProbeError: If ffprobe is unable to successfully probe the file.

    """

    probe_response = subprocess.run(
        ['/usr/bin/ffprobe', '-v', 'error', '-show_format', '-show_streams',
         '-of', 'json', file_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if probe_response.returncode:
        raise ProbeError(file_name, probe_response.stderr.decode('utf-8')
                         .strip(os.linesep))
    else:
        title, size, bitrate, container_format = [None for _ in range(4)]
        probe_info = json.loads(probe_response.stdout)

        duration = float(probe_info['format']['duration'])
        streams = {int(stream['index']): build_stream(stream)
                   for stream in probe_info['streams']}

        if ('tags' in probe_info['format']
                and 'title' in probe_info['format']['tags']):
            title = probe_info['format']['tags']['title']
        if 'size' in probe_info['format']:
            file_bytes = int(probe_info['format']['size'])
            size = round(bitmath.MiB(bytes=file_bytes).value, 2)
        if 'bit_rate' in probe_info['format']:
            bits = int(probe_info['format']['bit_rate'])
            bitrate = round(bitmath.Mib(bits=bits).value, 2)
        if 'format_name' in probe_info['format']:
            container_format = probe_info['format']['format_name']

    return Container(file_name, duration, streams, title=title, size=size,
                     bitrate=bitrate, container_format=container_format)


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
            subtitle.display()
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


def select_streams(processor):
    """Prompt the user to select streams for processing.

    Args:
        processor (Processor): The Processor that the user will select Streams
        from it's Container.

    Raises:
        UserCancelError: If the user cancels selecting streams.

    """

    try:
        processor.container.display()
        query = 'Which streams would you like'
        streams = click.prompt(query,
                               type=SelectedStreams(processor.container))
        processor.streams = streams
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled selecting streams.')


def edit_stream_options(container):
    """Prompt the user to select a stream. Edit that stream's options.

    Args:
        container (Container): The Container with streams to be edited

    Raises:
        UserCancelError: If the user cancels editing a stream.

    """

    container.display()
    indices = [str(i) for i, s in container.streams.items()
               if s.type in ['audio', 'video']]
    stream = container.streams[int(multiple_choice('Select a stream:',
                                                   indices))]
    if stream.type == 'video':
        if stream.codec == 'h264' and yes_no('Copy stream?'):
            stream.crf = 0
        elif yes_no('Use default crf?'):
            stream.crf = 18
        else:
            crf = click.prompt('Enter crf', type=click.IntRange(0, 51))
            stream.crf = crf
    elif stream.type == 'audio':
        if stream.codec == 'aac' and yes_no('Copy stream?'):
            stream.custom_bitrate = None
        elif stream.bitrate and yes_no('Use source bitrate '
                                       '({}Kib/s)?'.format(stream.bitrate)):
            stream.custom_bitrate = stream.bitrate
        elif yes_no('Use default bitrate (384Kib/s)?'):
            stream.custom_bitrate = 384
        else:
            stream.custom_bitrate = click.prompt('Enter bitrate',
                                                 type=click.IntRange(0, 5000))


def change_file_name(processor):
    """Prompt the user to specify a name for the output file.

    Args:
        porcessor (Processor): The Processor that will make the file.

    Raises:
        UserCancelError: If the user cancels entering a name.

    """

    default = pathlib.PurePath(processor.container.file_name).stem + '.mp4'
    if yes_no('Use default file name ({})?'.format(default)):
        processor.output_name = default
    else:
        try:
            name = click.prompt('Enter output file name (without extension)')
            processor.output_name = name + '.mp4'
        except click.exceptions.Abort:
            raise UserCancelError('Cancelled editing file name.')


def build_containers(file_list):
    """Utility function to build a list of Container objets given a list of
        filenames.

    Note:
        If a container fails to build as the result of a ffprobe error, that
            error is echoed, and the building continues. If no containers are
            built, return and empty list.

    Args:
        file_list (list): File names (str) to attempt to build into containers.

    Returns:
        list: Succesfully built containers.

    """

    containers = []
    for file in file_list:
        try:
            container = build_container(file)
            containers.append(container)
        except ProbeError as _e:
            click.secho('Warning: Unable to process {}'.format(_e.file_name),
                        fg='red')
            click.echo(_e.message)
    return containers


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
        container.display()


@cli.command()
@click.pass_context
def convert(ctx):
    """Convert video file(s)"""

    containers = build_containers(ctx.obj['FILES'])
    processors = []
    for container in containers:
        processor = Processor(container)
        while True:
            processor.display()
            char = multiple_choice(
                'Convert file?', ['y', 'n', 'a', 'r', 's', 'e', 'c', 'd'],
                ('yes/no/{add/remove} subtitle file/{select/edit} streams/'
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
                    select_streams(processor)
                elif char == 'e':
                    edit_stream_options(container)
                elif char == 'c':
                    change_file_name(processor)
                elif char == 'd':
                    click.secho('Command:', fg='cyan', bold=True)
                    click.echo(' '.join(processor.build_command()))
            except UserCancelError as _e:
                click.secho('{}Warning: {}'.format(os.linesep, _e.message),
                            fg='red')
            if char == 'y':
                processor.execute()
                processors.append(processor)
            if char in ['y', 'n']:
                break

    total_ms = sum([p.container.microseconds for p in processors])
    label = 'Processing {} files:'.format(len(processors))
    with click.progressbar(length=total_ms, label=label) as pr_bar:
        while processors:
            for proc in processors:
                if proc.process.poll() is not None:
                    if proc.process.returncode:
                        click.secho('Warning: ffmpeg error while converting'
                                    '{}'.format(proc.container.file_name),
                                    fg='red')
                        click.echo(proc.process.communicate()[1]
                                   .strip(os.linesep))
                    pr_bar.update(proc.container.microseconds - proc.progress)
                    processors.remove(proc)
                else:
                    with open(proc.temp_file.name, 'r') as status:
                        line_list = status.readlines()
                    microsec = 0
                    for line in reversed(line_list):
                        if line.split('=')[0] == 'out_time_ms':
                            if line.split('=')[1].strip(os.linesep).isdigit():
                                microsec = int(line.split('=')[1])
                                break
                    if microsec:
                        pr_bar.update(microsec - proc.progress)
                        proc.progress = microsec
            time.sleep(1)


if __name__ == '__main__':
    cli()
