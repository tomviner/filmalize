"""A simple tool for converting video files.

System Dependencies:
    * ffmpeg

Todo:
    * Config file
    * Convert command
    * Filename whitelist?
    * probe_file:
        * Raise error on ffmpeg error
        * Test Filename
    * display_file:
        * Split up?
    * Tests

"""

import os
import subprocess
import json
import datetime

import click
import bitmath

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

def probe_file(file_name):
    """Utility function, uses ffprobe to extract information about a file.

    Args:
        file_name (str): The file to probe.

    Returns:
        json: Detailed file information from ffprobe.
        None: If ffprobe does not return cleanly.

    """

    probe_info = subprocess.run(['/usr/bin/ffprobe', '-v', 'error', '-show_format',
        '-show_streams', '-of', 'json', file_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if probe_info.returncode:
        click.echo('ffprobe warning - {}'.format(probe_info.stderr.decode('utf-8').strip('\n')))
        return None
    else:
        return json.loads(probe_info.stdout)

def display_file(file_info):
    """Utility function to display the salient information about a file.

    Args:
        file_info (json): json-formatted ffprobe results including at least
            format and stream information.
    Returns:
        dict: A dictionary with keys that are the stream indexes from the
            file_info and with values that are dictionaries containing
            information about the respective streams specifications.
    """

    if 'tags' in file_info['format'] and 'title' in file_info['format']['tags']:
        click.echo(click.style('Title: {}'.format(file_info['format']['tags']['title']),
            fg='cyan'))
    if 'filename' in file_info['format']:
        click.echo(click.style('File: {}'.format(file_info['format']['filename']), fg='magenta'))

    file_description = []
    if 'duration' in file_info['format']:
        seconds = round(float(file_info['format']['duration']), 0)
        file_description.append('Length: {}'.format(datetime.timedelta(seconds=seconds)))
    if 'size' in file_info['format']:
        length = round(bitmath.MiB(bytes=int(file_info['format']['size'])).value, 2)
        file_description.append('Size: {}MiB'.format(length))
    if 'bit_rate' in file_info['format']:
        bitrate = round(bitmath.Mib(bits=int(file_info['format']['bit_rate'])).value, 2)
        file_description.append('Bitrate: {}MiB/s'.format(bitrate))
    if 'format_name' in file_info['format']:
        file_description.append('Container: {}'.format(file_info['format']['format_name']))
    click.echo(' | '.join(file_description))

    streams = {}
    for stream in file_info['streams']:
        index = stream['index']
        stream_header = 'Stream {}:'.format(index)
        streams[index] = {}

        stream_info = []
        if 'codec_type' in stream:
            stream_type = stream['codec_type']
            stream_info.append(stream_type)
            streams[index]['type'] = stream_type
        if 'codec_name' in stream:
            stream_info.append(stream['codec_name'])
            streams[index]['codec'] = stream['codec_name']
        if 'tags' in stream and 'language' in stream['tags']:
            stream_info.append(stream['tags']['language'])
        if 'disposition' in stream and 'default' in stream['disposition']:
            if stream['disposition']['default']:
                stream_info.append('default')
        click.echo('  ' + click.style(stream_header, fg='green', bold=True) + ' '
            + click.style(' '.join(stream_info), fg='yellow'))

        if 'tags' in stream and 'title' in stream['tags']:
            click.echo('    Title: {}'.format(stream['tags']['title']))

        stream_specs = []
        if stream_type == 'video':
            if 'height' in stream and 'width' in stream:
                resolution = str(stream['width']) + 'x' + str(stream['height'])
                stream_specs.append('Resolution: {}'.format(resolution))
            elif 'coded_height' in stream and 'coded_width' in stream:
                resolution = str(stream['coded_width']) + 'x' + str(stream['coded_height'])
                stream_specs.append('Resolution: {}'.format(resolution))
            if 'bitrate' in stream:
                bitrate = round(bitmath.Mib(bits=int(stream['bit_rate'])).value, 2)
                stream_spcs.append('Bitrate: {}Mib/s'.format(bitrate))
                streams[index]['bitrate'] = bitrate
            if 'field_order' in stream:
                stream_specs.append('Scan: {}'.format(stream['field_order']))
        elif stream_type == 'audio':
            if 'channel_layout' in stream:
                stream_specs.append('Channels: {}'.format(stream['channel_layout']))
            if 'bit_rate' in stream:
                bitrate = round(bitmath.Kib(bits=int(stream['bit_rate'])).value)
                stream_specs.append('Bitrate: {}Kib/s'.format(bitrate))
                streams[index]['bitrate'] = bitrate
        if stream_specs:
            click.echo('    ' + ' | '.join(stream_specs))

    return streams

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

def select_streams(input_streams):
    """Function to ascertain which streams from the input file to include in
        the output.

    If there are only two streams, it assumes that they must be the streams
    that we need. Otherwise, ask the user which streams to include.

    Args:
        input_streams (dict): A dictionary with keys that are the stream
            indexes from the file_info and with values that are dictionaries
            containing information about the respective streams specifications.
    Returns:
        list: The streams to include in the output

    """

    if len(input_streams.keys()) == 2:
        return [0, 1]

    acceptable_responses = input_streams.keys()
    ask = 'Which streams would you like?'
    prompt = ask + ' [{}]'.format(' '.join([str(r) for r in acceptable_responses]))
    while True:
        r = click.prompt(prompt)
        responses = [int(response) for response in r.split(' ')]
        acceptable, video, audio = True, False, False
        for response in responses:
            if response not in acceptable_responses:
                acceptable = False
                break
            if input_streams[response]['type'] == 'audio':
                audio = True
            elif input_streams[response]['type'] == 'video':
                video = True
        if acceptable and audio and video:
            return responses
        else:
            click.echo('Invalid input. Separate streams with a single space.')
            click.echo('You must include at least one audio and one video stream.')

def build_map_options(output_streams):
    """Generate -map options for our conversion ffmpeg command from each
        selected output stream.

    Returns:
        list: ffmpeg -map option for each selected output stream.

    """

    return [c for stream in output_streams for c in ['-map', '0:{}'.format(stream)]]

def build_video_options(stream):
    """Build option list for copying or transcoding video streams.

    If the input stream is already h264, it is simply copied to the output.
    Otherwise, the stream will be transcoded. If so, the user is offered the
    option of specifying a crf, or accepting the default of 18.

    Args:
        stream (dict): A dictionary with spec information about the video
            stream to be copied/transcoded to the output.

    Returns:
        list: ffmpeg options for copying or transcoding video streams

    """
    if 'codec' in stream and stream['codec'] == 'h264':
        return ['-c:v', 'copy']
    else:
        if not yes_no('Video needs to be transcoded. Use default crf (18)?'):
            while True:
                f = click.prompt('Specify crf [0-51]')
                if f.isdigit() and int(f) in range(52):
                    crf = int(f)
                    break
                else:
                    click.echo('Invalid input, try again...')
        else:
            crf = 18
        return ['-c:v', 'libx264', '-preset', 'slow', '-crf', crf, '-pix_fmt', 'yuv420p']

def build_audio_options(stream):
    """Build option list for copying or transcoding audio streams.

    If the input stream is already aac, it is simply copied to the output.
    Otherwise, the stream will be transcoded. If the input stream's bitrate
    cannot be detected, the user is offerred the  option of specifying a
    bitrate, or accepting the default of 384kib/s.

    Args:
        stream (dict): A dictionary with spec information about the audio
            stream to be copied/transcoded to the output.

    Returns:
        list: ffmpeg options for copying or transcoding audio streams

    """
    if 'codec' in stream and stream['codec'] == 'aac':
        return ['-c:a', 'copy']
    elif 'bitrate' in stream:
        return ['-c:a', 'aac', '-b:a', '{}k'.format(stream['bitrate'])]
    else:
        click.echo('Audio needs to be transcoded, cannot determine existing bitrate.')
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
        return ['-c:a', 'aac', '-b:a', '{}k'.format(bitrate)]

def build_filename(input_filename):
    """Build output file name.

    Ask the user if they would like to change the output file name. Allow
    them to specify one if they so desire.

    Args:
        input_filename (string)

    Returns:
        list: Wrapping one element; the output filename.

    """
    name = '.'.join(input_filename.split('.')[:-1])
    if not yes_no('Use default output filename: {} (.mp4)?'.format(name)):
        while True:
            f = click.prompt('Specify filename (without extension)')
            if f:
                name = '\ '.join(f.split(' '))
                break
            else:
                click.echo('You must specify a filename. Try again...')
    return [name + '.mp4']

@click.group()
@click.option('-f', '--file', type=click.Path(exists=True), help='Specify a file.')
@click.option('-d', '--directory', type=click.Path(exists=True), help='Specify a directory.')
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

    for file in ctx.obj['FILES']:
        file_info = probe_file(file)
        if file_info:
            display_file(file_info)

@cli.command()
@click.pass_context
def convert(ctx):
    """Convert video file(s)"""

    for file in ctx.obj['FILES']:
        file_info = probe_file(file)
        if file_info:
            input_streams = display_file(file_info)
            if yes_no('Convert file?'):
                output_streams = select_streams(input_streams)
                output_command = ['ffmpeg', '-i', file]
                output_command.extend(build_map_options(output_streams))
                for stream in output_streams:
                    if input_streams[stream]['type'] == 'video':
                        output_command.extend(build_video_options(input_streams[stream]))
                    elif input_streams[stream]['type'] == 'audio':
                        output_command.extend(build_audio_options(input_streams[stream]))
                    elif input_streams[stream]['type'] == 'audio':
                        output_command.extend(['-c:s', 'mov_text'])
                output_command.extend(build_filename(file.split('/')[-1]))
                click.echo(' '.join(output_command))

if __name__ == '__main__':
    cli(obj={})
