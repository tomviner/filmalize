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
    * Remove subtitle files
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
        for s in selected:
            if not s.isdigit():
                self.fail('Invalid input. Enter stream indices separated by a single space.')
            stream = int(s)
            if stream not in self.streams.keys():
                self.fail('Invalid input. {} is not an available stream index.'.format(stream))
            elif self.streams[stream].type == 'audio':
                audio = True
            elif self.streams[stream].type == 'video':
                video = True
        if audio and video:
            return [int(s) for s in selected]
        else:
            self.fail('Invalid input. You must include at least one audio and one video stream.')

class Container:
    """Multimedia container file object."""

    def __init__(self, file_name):
        """Initialize container object.

        First, attempt to probe the file with ffprobe. If the probe is
        succesful, finish instatiation using the results of the probe,
        building Stream instances as necessary.

        Args:
            file_name (str): The multimedia container file to represent.

        Raises:
            ProbeError: If ffprobe does not return cleanly.

        """

        self.file_name = file_name
        self.title, self.duration, self.size, self.bitrate, self.format = ['' for _ in range(5)]
        self.microseconds = 1
        self.streams = {}
        self.subtitle_files = []

        probe_response = subprocess.run(['/usr/bin/ffprobe', '-v', 'error', '-show_format',
            '-show_streams', '-of', 'json', self.file_name], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        if probe_response.returncode:
            raise ProbeError(file_name, probe_response.stderr.decode('utf-8').strip(os.linesep))
        else:
            probe_info = json.loads(probe_response.stdout)
            if 'tags' in probe_info['format'] and 'title' in probe_info['format']['tags']:
                self.title = probe_info['format']['tags']['title']
            if 'duration' in probe_info['format']:
                duration = float(probe_info['format']['duration'])
                self.microseconds = int(duration * 1000000)
                self.length = datetime.timedelta(seconds=round(duration, 0))
            if 'size' in probe_info['format']:
                self.size = round(bitmath.MiB(bytes=int(probe_info['format']['size'])).value, 2)
            if 'bit_rate' in probe_info['format']:
                bits=int(probe_info['format']['bit_rate'])
                self.bitrate = round(bitmath.Mib(bits=bits).value, 2)
            if 'format_name' in probe_info['format']:
                self.container_format = probe_info['format']['format_name']

            for stream in probe_info['streams']:
                self.streams[int(stream['index'])] = Stream(stream)

    def add_subtitle_file(self, file_name, encoding):
        """Add an external subtitle file. Allow the user to set a custom
        encoding.

        Args:
            file_name (str): The name of the subtitle file.
            encoding (str): The encoding of the subtitle file.

        """

        index = len(self.subtitle_files.keys()) + 1
        self.subtitle_files[index] = SubtitleFile(index, file_name, encoding)

    def display(self):
        """Echo a pretty representation of the Container."""

        if self.title:
            click.echo(click.style('Title: {}'.format(self.title),fg='cyan'))
        click.echo(click.style('File: {}'.format(self.file_name), fg='magenta'))

        file_description = []
        if self.length:
            file_description.append('Length: {}'.format(self.length))
        if self.size:
            file_description.append('Size: {}MiB'.format(self.size))
        if self.bitrate:
            file_description.append('Bitrate: {}MiB/s'.format(self.bitrate))
        if self.container_format:
            file_description.append('Container: {}'.format(self.container_format))
        click.echo(' | '.join(file_description))

        for index, stream in self.streams.items():
            stream.display()

        for subtitle in self.subtitle_files:
            subtitle.display()

class Stream:
    """Multimedia stream object."""

    def __init__(self, stream_info):
        """Initialize stream object.

        Instantiate Stream instance variables, when available, using the info
        passed in stream_info, defaulting to None if not specified. Generate
        default ffmpeg options.

        Args:
            stream_info (dict): Stream information as reported by ffprobe.

        """

        [self.type, self.name, self.language, self.default, self.title, self.resolution,
            self.bitrate, self.scan, self.channels, self.bitrate] = [None for _ in range(10)]
        self.index = stream_info['index']
        self.options = []
        self.option_summary = 'copy'

        if 'codec_type' in stream_info:
            self.type = stream_info['codec_type']
        if 'codec_name' in stream_info:
            self.codec = stream_info['codec_name']
        if 'tags' in stream_info and 'language' in stream_info['tags']:
            self.language = stream_info['tags']['language']
        if 'disposition' in stream_info and 'default' in stream_info['disposition']:
            self.default = True if stream_info['disposition']['default'] else False

        if 'tags' in stream_info and 'title' in stream_info['tags']:
            self.title = stream_info['tags']['title']

        if self.type == 'video':
            if 'height' in stream_info and 'width' in stream_info:
                self.resolution = str(stream_info['width']) + 'x' + str(stream_info['height'])
            elif 'coded_height' in stream and 'coded_width' in stream:
                width = str(stream_info['coded_width'])
                height = str(stream_info['coded_height'])
                self.resolution = width + 'x' + height
            if 'bitrate' in stream_info:
                self.bitrate = round(bitmath.Mib(bits=int(stream_info['bit_rate'])).value, 2)
            if 'field_order' in stream_info:
                self.scan = stream_info['field_order']
            self.generate_video_options()
        elif self.type == 'audio':
            if 'channel_layout' in stream_info:
                self.channels = stream_info['channel_layout']
            if 'bit_rate' in stream_info:
                bit_rate = round(bitmath.Kib(bits=int(stream_info['bit_rate'])).value)
                self.bitrate = bit_rate
            self.generate_audio_options()
        elif self.type == 'subtitle':
            self.options.extend(['mov_text'])
            self.option_summary = 'transcode -> mov_text'

    def generate_video_options(self, crf=None):
        """Generate ffmpeg codec/bitrate options for this video stream.

        If a crf value is specified, use that to transcode the stream.
        Otherwise, if the stream is already h264, copy it to the output, or
        transcode it using the default crf, 18.

        Args:
            crf (int): The constant rate factor to apply while transcoding.

        """

        if self.codec == 'h264' and not crf:
            self.options = ['copy']
            self.option_summary = 'copy'
        else:
            crf = 18 if not crf else crf
            self.options = ['libx264', '-preset', 'slow', '-crf', str(crf), '-pix_fmt',
                'yuv420p']
            self.option_summary = 'transcode -> h264, crf={}'.format(crf)

    def generate_audio_options(self, br=None):
        """Generate ffmpeg codec/bitrate options for this audio stream.

        If a bitrate is specified, use that to transcode the stream. Otherwise,
        if the stream is already aac, copy it to the output, or transcode it
        using the input stream's bitrate, if available, or 384kib/s.

        Args:
            br (int): The bitrate, in kib/s, to use while transcoding.

        """

        if self.codec == 'aac' and not br:
            self.options = ['copy']
            self.option_summary = 'copy'
        else:
            br = self.bitrate if not br else br
            self.options = ['aac', '-b:a', '{}k'.format(br)]
            self.option_summary = 'transcode -> aac, bitrate={}kib/s'.format(br)

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
        click.echo('  ' + click.style(stream_header, fg='green', bold=True) + ' '
            + click.style(' '.join(stream_info), fg='yellow'))

        if self.title:
            click.echo('    Title: {}'.format(self.title))

        stream_specs = []
        if self.type == 'video':
            if self.resolution:
                stream_specs.append('Resolution: {}'.format(self.resolution))
            if self.bitrate:
                stream_spcs.append('Bitrate: {}Mib/s'.format(self.bitrate))
            if self.scan:
                stream_specs.append('Scan: {}'.format(self.scan))
        elif self.type == 'audio':
            if self.channels:
                stream_specs.append('Channels: {}'.format(self.channels))
            if self.bitrate:
                stream_specs.append('Bitrate: {}Kib/s'.format(self.bitrate))
        if stream_specs:
            click.echo('    ' + ' | '.join(stream_specs))

class SubtitleFile:
    """Subtitle file object."""

    def __init__(self, file_name, encoding):
        self.file_name = file_name
        self.encoding = encoding
        self.options = ['mov_text']

    def display(self):
        """Echo a pretty representation of the subtitle file."""

        click.echo(click.style('Subtitle File: {}'.format(self.file_name), fg='magenta'))
        click.echo('  Encoding: {}'.format(self.encoding))

class Processor:
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
        audio, video = None, None
        for index, stream in self.container.streams.items():
            if not audio and stream.type == 'audio':
                audio = True
                self.streams.append(index)
            elif not video and stream.type == 'video':
                video = True
                self.streams.append(index)
        self.output_name = pathlib.PurePath(self.container.file_name).stem + '.mp4'
        self.progress = 0

    def execute(self):
        """Start processing the container."""

        self.process = subprocess.Popen(self.build_command(), stderr=subprocess.PIPE,
            universal_newlines=True)

    def display(self):
        """Echo a pretty representation of the processing actions to take."""

        self.container.display()
        click.echo(click.style('Filmalize Actions:', fg='cyan', bold=True))
        for stream in self.streams:
            header = 'Stream {}: '.format(stream)
            info = self.container.streams[stream].option_summary
            click.echo(click.style(header, fg='green', bold=True) + click.style(info, fg='yellow'))
        click.echo(click.style('Output File: {}'.format(self.output_name), fg='magenta'))

    def build_command(self):
        """Build the ffmpeg command to process this container.

        Generate appropriate ffmpeg options to process the selected streams.

        Returns:
            list: The ffmpeg command and options to execute.

        """

        command = ['/usr/bin/ffmpeg', '-nostdin', '-progress', self.temp_file.name, '-v', 'error',
            '-y', '-i', self.container.file_name]
        for subtitle in self.container.subtitle_files:
            command.extend(['-sub_charenc', subtitle.encoding, '-i', subtitle.file_name])
        for stream in self.streams:
            command.extend(['-map', '0:{}'.format(stream)])
        for index, subtitle in enumerate(self.container.subtitle_files):
            command.extend(['-map', '{}:0'.format(index + 1)])
        audio_streams = 0
        video_streams = 0
        subtitle_streams = 0
        output_streams = [self.container.streams[s] for s in self.streams]
        for stream in output_streams:
            if stream.type == 'video':
                command.extend(['-c:v:{}'.format(video_streams)])
                video_streams += 1
            elif stream.type == 'audio':
                command.extend(['-c:a:{}'.format(audio_streams)])
                audio_streams += 1
            elif stream.type == 'subtitle':
                command.extend(['-c:s:{}'.format(subtitle_streams)])
                subtitle_streams += 1
            command.extend(stream.options)
        for subtitle in self.container.subtitle_files:
            command.extend(['-c:s:{}'.format(subtitle_streams)])
            subtitle_streams += 1
            command.extend(subtitle.options)
        command.extend([os.path.join(os.path.dirname(self.container.file_name), self.output_name)])
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
        c = click.getchar()
        click.echo()
        if c == 'y':
            return True
        elif c == 'n':
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
        c = click.getchar()
        click.echo()
        if c in responses:
            return c
        else:
            click.echo('Invalid input, try again...')

def add_subtitles(container):
    """Add an external subtitle file. Allow the user to set a custom encoding.

    Args:
        container (Container): The Container to add the subtitle file to.

    Raises:
        UserCancelError: If the user cancels adding a subtitle file.

    """

    sub_file, encoding = sub_file_prompt()
    while True:
        c = multiple_choice('Continue?', ['a', 'r', 's', 'c'],
            'accept / retry / specify custom / cancel')
        if c == 'a':
            container.subtitle_files.append(SubtitleFile(sub_file, encoding))
            break
        elif c == 'r':
            sub_file, encoding = sub_file_prompt()
        elif c == 's':
            encoding = click.prompt('Enter custom encoding')
            click.echo('Custom encoding specified: {}'.format(encoding))
        elif c == 'c':
            raise UserCancelError('Cancelled subtitle file addition.')

def remove_subtitles(container):
    """Remove an external subtitle file.

    Args:
        container (Container): The Container to remove the subtitle file from.

    Raises:
        UserCancelError: If the user cancels removing a subtitle file, or if
        there are no subtitle files to remove.

    """

    if len(container.subtitle_files) == 0:
        raise UserCancelError('There are no subtitle files to remove.')
    else:
        for index, subtitle in enumerate(container.subtitle_files):
            click.echo(click.style('Number: {}'.format(index), fg='cyan', bold=True))
            subtitle.display()
        acceptable = [str(i) for i in range(len(container.subtitle_files))] + ['c']
        action = multiple_choice('Enter the file number to remove, or c to cancel:', acceptable)
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
        sub_file = click.prompt('Enter subtitle file name', type=click.Path(exists=True,
            dir_okay=False, readable=True))
    except click.exceptions.Abort:
        raise UserCancelError('Cancelled adding subtitle file.')

    with open(sub_file, mode='rb') as f:
        line = f.readline()
    detected = chardet.detect(line)
    click.echo('Subtitle file encoding detected as {}, with {}% confidence'.format(
        detected['encoding'], int(detected['confidence']) * 100))
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
        streams = click.prompt(query, type=SelectedStreams(processor.container))
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
    indices = [str(i) for i in container.streams.keys()]
    stream = container.streams[int(multiple_choice('Select a stream:', indices))]
    if stream.type == 'video':
        if stream.codec == 'h264' and yes_no('Copy stream?'):
            stream.generate_video_options()
        elif yes_no('Use default crf?'):
            stream.generate_video_options(18)
        else:
            crf = click.prompt('Enter crf', type=click.IntRange(0, 51))
            stream.generate_video_options(crf)
    elif stream.type == 'audio':
        if stream.codec == 'aac' and yes_no('Copy stream?'):
            stream.generate_audio_options()
        elif stream.bitrate and yes_no('Use source bitrate ({}kib/s)?'.format(stream.bitrate)):
            stream.generate_audio_options(stream.bitrate)
        elif yes_no('Use default bitrate (384kib/s)?'):
            stream.generate_audio_options(384)
        else:
            br = click.prompt('Enter bitrate', type=click.IntRange(0, 5000))
            stream.generate_audio_options(br)
    else:
        click.echo('Sorry: you selected a stream that cannot be edited.')

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
            c = Container(file)
            containers.append(c)
        except ProbeError as e:
            click.echo(click.style('Warning: Unable to process {}'.format(e.file_name), fg='red'))
            click.echo(e.message)
    return containers

@click.group()
@click.option('-f', '--file', type=click.Path(exists=True, dir_okay=False, readable=True),
    help='Specify a file.')
@click.option('-d', '--directory', type=click.Path(exists=True, file_okay=False, readable=True),
    help='Specify a directory.')
@click.option('-r', '--recursive', is_flag=True, help='Operate recursively.')
@click.pass_context
def cli(ctx, file, directory, recursive):
    """A simple tool for converting video files.

    By default filmalize operates on all files in the current directory. If
    desired, you may specify an individual file or a different working
    directory. Directory operation may be recursive. A command is required.

    """

    exclusive(ctx.params, ['file', 'directory'], 'a file may not be specified with a directory')
    exclusive(ctx.params, ['file', 'recursive'],
        'a file may not be specified with the recursive flag')

    ctx.obj = {}

    if file:
        ctx.obj['FILES'] = [file]
    else:
        directory = directory if directory else '.'
        if recursive:
            ctx.obj['FILES'] = sorted([os.path.join(root, file) for root, dirs, files
                in os.walk(directory) for file in files])
        else:
            ctx.obj['FILES'] = sorted([dir_entry.path for dir_entry in os.scandir(directory)
                if dir_entry.is_file()])

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
            c = multiple_choice('Convert file?', ['y', 'n', 'a', 'r', 's', 'e', 'c', 'p'],
                'yes/no/{add/remove} subtitle file/{select/edit} streams/change filename/'
                + 'display command')
            try:
                if c == 'n':
                    raise UserCancelError('Cancelled converting {}'.format(container.file_name))
                elif c == 'a':
                    add_subtitles(container)
                elif c == 'r':
                    remove_subtitles(container)
                elif c == 's':
                    select_streams(processor)
                elif c == 'e':
                    edit_stream_options(container)
                elif c == 'c':
                    change_file_name(processor)
                elif c == 'd':
                    click.echo(click.style('Command:', fg='cyan', bold=True))
                    click.echo(' '.join(processor.build_command()))
            except UserCancelError as e:
                click.echo(click.style('{}Warning: {}'.format(os.linesep, e.message), fg='red'))
            if c == 'y':
                processor.execute()
                processors.append(processor)
            if c in ['y', 'n']:
                break

    total_ms = sum([p.container.microseconds for p in processors])
    label = 'Processing {} files:'.format(len(processors))
    with  click.progressbar(length=total_ms, label=label) as bar:
        while processors:
            for processor in processors:
                if processor.process.poll() != None:
                    if processor.process.returncode:
                        click.echo(click.style('Warning: ffmpeg error while converting {}'.format(
                            processor.container.file_name), fg='red'))
                        click.echo(processor.process.communicate()[1].strip(os.linesep))
                    bar.update(processor.container.microseconds - processor.progress)
                    processors.remove(processor)
                else:
                    with open(processor.temp_file.name, 'r') as status:
                        line_list = status.readlines()
                    ms = 0
                    for line in reversed(line_list):
                        if line.split('=')[0] == 'out_time_ms':
                            if line.split('=')[1].strip(os.linesep).isdigit():
                                ms = int(line.split('=')[1])
                                break
                    if ms:
                        bar.update(ms - processor.progress)
                        processor.progress = ms
            time.sleep(1)

if __name__ == '__main__':
    cli()
