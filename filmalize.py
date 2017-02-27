"""A simple tool for converting video files.

System Dependencies:
    * ffmpeg

Todo:
    * Config file
    * Filename whitelist?
    * Tests
    * Rewrite processor
    * Default to yes
    * Status interrupts
    * Specify metadata edits

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

class CancelProcessorError(Error):
    """Custom Exception for when the user cancels processing a file."""

    def __init__(self, file_name):
        self.file_name = file_name

class CancelSubtitleError(Error):
    """Custom Exception for when the user cancels adding a subtitle file."""

    def __init__(self, message=None):
        self.message = message if message else ''

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
        self.streams, self.subtitle_files = {}, {}

        probe_response = subprocess.run(['/usr/bin/ffprobe', '-v', 'error', '-show_format',
            '-show_streams', '-of', 'json', self.file_name], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        if probe_response.returncode:
            raise ProbeError(file_name, probe_response.stderr.decode('utf-8').strip('\n'))
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

        for index, subtitle in self.subtitle_files.items():
            subtitle.display()

class Stream:
    """Multimedia stream object."""

    def __init__(self, stream_info):
        """Initialize stream object.

        Instantiate Stream instance variables, when available, using the info
        passed in stream_info, defaulting to None if not specified.

        Args:
            stream_info (dict): Stream information as reported by ffprobe.

        """

        [self.type, self.name, self.language, self.default, self.title, self.resolution,
            self.bitrate, self.scan, self.channels, self.bitrate] = [None for _ in range(10)]
        self.index = stream_info['index']

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
        elif self.type == 'audio':
            if 'channel_layout' in stream_info:
                self.channels = stream_info['channel_layout']
            if 'bit_rate' in stream_info:
                bit_rate = round(bitmath.Kib(bits=int(stream_info['bit_rate'])).value)
                self.bitrate = bit_rate

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

    def __init__(self, index, file_name, encoding):
        self.index = index
        self.file_name = file_name
        self.encoding = encoding

    def display(self):
        """Echo a pretty representation of the subtitle file."""

        click.echo(click.style('Subtitle File: {}'.format(self.file_name), fg='magenta'))
        click.echo('  Index: {} | Encoding: {}'.format(self.index, self.encoding))

class Processor:
    """Container processor object."""

    def __init__(self, container):
        """Initialize Processor object.

        Build a ffmpeg command to process the given Container. Prompt the
        user for confirmation. The user may accept, decline, or retry.

        Args:
            container (Container): The container object to process.

        Raises:
            CancelProcessorError: If the user declines to process the
                container.

        """

        self.container = container
        self.temp_file = tempfile.NamedTemporaryFile()
        self.output_command = self.build_command()
        self.progress = 0
        while True:
            confirm = False
            click.echo('Generated Command:')
            click.echo(' '.join(self.output_command))
            c = multiple_choice('yes / no / retry', 'Continue?', ['y', 'n', 'r'])
            if c == 'y':
                break
            elif c == 'n':
                raise CancelProcessorError(self.container.file_name)
            elif c == 'r':
                self.output_command = self.build_command()


    def execute(self):
        """Start processing the container."""

        self.process = subprocess.Popen(self.output_command, stderr=subprocess.PIPE,
            universal_newlines=True)

    def build_command(self):
        """Build the ffmpeg command to process this container.

        Prompt the user to pick which streams to include, then generate
        appropriate ffmpeg options to process those streams. Prompt the user
        for an output filename.

        Returns:
            list: The ffmpeg command to process this container.

        """

        output_streams = [self.container.streams[s] for s in self.select_streams()]
        command = ['/usr/bin/ffmpeg', '-nostdin', '-progress', self.temp_file.name, '-v', 'error',
            '-y', '-i', self.container.file_name]
        for index, subtitle in self.container.subtitle_files.items():
            command.extend(['-i', subtitle.file_name])
        self.audio_streams = 0
        self.video_streams = 0
        self.subtitle_streams = 0
        for stream in output_streams:
            if stream.type == 'video':
                command.extend(self.add_video_options(stream))
            elif stream.type == 'audio':
                command.extend(self.add_audio_options(stream))
            elif stream.type == 'subtitle':
                command.extend(self.add_subtitle_options(stream))
        for index, subtitle in self.container.subtitle_files.items():
            command.extend(self.add_subtitle_file_options(subtitle))
        command.extend(self.add_filename())
        return command

    def select_streams(self):
        """Which streams from the input file does the user want in the output.

        If there are only two streams, return those. Otherwise, ask the user
        which streams to include.

        Returns:
            list: The streams to include in the output

        """

        if len(self.container.streams.keys()) == 2:
            return self.container.streams.keys()

        audio, video = None, None
        for index, stream in self.container.streams.items():
            if audio == None and stream.type == 'audio':
                audio = index
            elif video == None and stream.type == 'video':
                video = index
        if yes_no('Use streams {} and {}?'.format(video, audio)):
                return([video, audio])

        acceptable_responses = self.container.streams.keys()
        ask = 'Which streams would you like?'
        prompt = ask + ' [{}]'.format(' '.join([str(r) for r in acceptable_responses]))
        while True:
            responses = click.prompt(prompt).strip().split(' ')
            acceptable, video, audio = True, False, False
            for r in responses:
                if not r.isdigit():
                    acceptable = False
                    break
                response = int(r)
                if response not in acceptable_responses:
                    acceptable = False
                    break
                if self.container.streams[response].type == 'audio':
                    audio = True
                elif self.container.streams[response].type == 'video':
                    video = True
            if acceptable and audio and video:
                return [int(r) for r in responses]
            else:
                click.echo('Invalid input. Separate streams with a single space.')
                click.echo('You must include at least one audio and one video stream.')

    def add_video_options(self, stream):
        """Add options for copying or transcoding a specified video stream to
        the output_command.

        If the input stream is already h264, it is simply copied to the output.
        Otherwise, the stream will be transcoded. If so, the user is offered the
        option of specifying a crf, or accepting the default of 18.

        Args:
            stream (Stream): Video Stream to be added to the output.

        Returns:
            list: The ffmpeg options for the given video stream.

        """

        command = ['-map', '0:{}'.format(stream.index)]
        if stream.codec == 'h264':
            command.extend(['-c:v:{}'.format(self.video_streams), 'copy'])
        else:
            click.echo('Stream {} (video) needs to be transcoded.'.format(stream.index))
            if not yes_no('Use default crf (18)?'):
                crf = click.prompt('Specify crf [0-51]', type=click.IntRange(0, 52))
            else:
                crf = 18
            command.extend(['-c:v:{}'.format(self.video_streams), 'libx264', '-preset', 'slow',
                '-crf', str(crf), '-pix_fmt', 'yuv420p'])

        self.video_streams += 1
        return command

    def add_audio_options(self, stream):
        """Add options for copying or transcoding a specified audio stream to
        the output_command.

        If the input stream is already aac, it is simply copied to the output.
        Otherwise, the stream will be transcoded. If the input stream's bitrate
        cannot be detected, the user is offerred the  option of specifying a
        bitrate, or accepting the default of 384kib/s.

        Args:
            stream (Stream): Audio Stream to be added to the output.

        Returns:
            list: The ffmpeg options for the given audio stream.

        """

        command = ['-map', '0:{}'.format(stream.index)]
        if stream.codec == 'aac':
            command.extend(['-c:a:{}'.format(self.audio_streams), 'copy'])
        elif stream.bitrate:
            bitrate = stream.bitrate
            command.extend(['-c:a:{}'.format(self.audio_streams), 'aac', '-b:a',
                '{}k'.format(bitrate)])
        else:
            click.echo('Stream {} (audio) needs to be transcoded.'.format(stream.index))
            if not yes_no('Use default bitrate (384kib/s)?'):
                while True:
                    r = click.prompt('Specify bitrate (just the number, units are kib/s)')
                    if r.isdigit():
                        bitrate = int(r)
                        break
                    else:
                        click.echo('Invalid input, try again...')
            else:
                bitrate = 384
            command.extend(['-c:a:{}'.format(self.audio_streams), 'aac',
                '-b:a:{}'.format(self.audio_streams), '{}k'.format(bitrate)])

        self.audio_streams += 1
        return command

    def add_subtitle_options(self, stream):
        """Add options for including a specified subtitle stream to the
        output_command. Subtitles will be converted to the mov_text format.

        Args:
            stream (Stream): Subtitle Stream to be added to the output.

        Returns:
            list: The ffmpeg options for the given subtitle stream.

        """

        command = ['-map', '0:{}'.format(stream.index)]
        command.extend(['-c:s:{}'.format(self.subtitle_streams), 'mov_text'])
        self.subtitle_streams += 1
        return command

    def add_subtitle_file_options(self, subtitle):
        """Add options for including a specified subtitle stream to the
        output_command. Subtitles will be converted to the mov_text format.

        Args:
            subtitle (SubtitleFile): The subtitle file for which to add
                options to the ffmpeg command.

        Returns:
            list: The ffmpeg options for the given subtitle file.

        """

        command = ['-map', '{}:0'.format(subtitle.index)]
        command.extend(['-c:s:{}'.format(self.subtitle_streams), 'mov_text'])
        self.subtitle_streams += 1
        return command

    def add_filename(self):
        """Add output filename to the output_command.

        Ask the user if they would like to change the output file name. Allow
        them to specify one if they so desire.

        Returns:
            list: Comprising one element; the output filename.

        """

        name = pathlib.PurePath(self.file_name).stem
        if not yes_no('Use default output filename: {} (.mp4)?'.format(name)):
            name = click.prompt('Specify filename (without extension)').strip()

        output_name = [os.path.join(os.path.basename(self.file_name), name + '.mp4')]
        return output_name


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

def multiple_choice(key, prompt, responses):
    """Utility function to ask the user a multple choice question."""

    while True:
        click.echo('Key: {}'.format(key))
        full_prompt = prompt + ' [{}]'.format('/'.join(responses))
        click.echo(full_prompt, nl=False)
        c = click.getchar()
        click.echo()
        if c in responses:
            return c
        else:
            click.echo('Invalid input, try again...')

def add_subtitles():
    """Add an external subtitle file. Allow the user to set a custom encoding.

    Raises:
        CancelSubtitleError: If the user cancels the operation.

    Returns:
        string: The subtitle file name
        string: The subtitle file encoding

    """

    sub_file, encoding = sub_file_prompt()
    while True:
        c = multiple_choice('accept / retry / specify custom / cancel', 'Continue?',
            ['a', 'r', 's', 'c'])
        if c == 'a':
            return sub_file, encoding
        elif c == 'r':
            sub_file, encoding = sub_file_prompt()
        elif c == 's':
            encoding = click.prompt('Enter custom encoding')
            click.echo('Custom encoding specified: {}'.format(encoding))
        elif c == 'c':
            raise CancelSubtitleError('Cancelled subtitle file addition.')

def sub_file_prompt():
    """Prompt the user to specify a subtitle file.

    Use chardet to detect the character encoding. Display the detected
    encoding and confidence to the user.

    Returns:
        string: The subtitle file name
        string: The subtitle file encoding

    """

    sub_file = click.prompt('Enter subtitle file name', type=click.Path(exists=True,
    dir_okay=False, readable=True))
    with open(sub_file, mode='rb') as f:
        line = f.readline()
    detected = chardet.detect(line)
    click.echo('Subtitle file encoding detected as {}, with {}% confidence'.format(
        detected['encoding'], int(detected['confidence']) * 100))
    return sub_file, detected['encoding']

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
        while True:
            container.display()
            c = multiple_choice('yes / no / add subtitles', 'Convert file?', ['y', 'n', 'a'])
            if c == 'a':
                try:
                    sub_file, encoding = add_subtitles()
                    container.add_subtitle_file(sub_file, encoding)
                except CancelSubtitleError as e:
                    click.echo('Warning: {}'.format(e.message))
            if c == 'y':
                try:
                    processor = Processor(container)
                    processor.execute()
                    processors.append(processor)
                except CancelProcessorError as e:
                    click.echo(click.style('Warning: Cancelled converting {}'.format(e.file_name),
                        fg='red'))
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
                        click.echo(processor.process.communicate()[1].strip('\n'))
                    bar.update(processor.container.microseconds - processor.progress)
                    processors.remove(processor)
                else:
                    with open(processor.temp_file.name, 'r') as status:
                        line_list = status.readlines()
                    ms = 0
                    for line in reversed(line_list):
                        if line.split('=')[0] == 'out_time_ms':
                            if line.split('=')[1].strip('\n').isdigit():
                                ms = int(line.split('=')[1])
                                break
                    if ms:
                        bar.update(ms - processor.progress)
                        processor.progress = ms
            time.sleep(1)

if __name__ == '__main__':
    cli()
