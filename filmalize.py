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
        * Split up
        * Test json
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
        file_info (json): The information to parse and display.

    """

    click.echo(click.style('File: ', fg='magenta', bold=True)
        + click.style(file_info['format']['filename'], fg='cyan'))
    length = datetime.timedelta(seconds=round(float(file_info['format']['duration']), 0))
    size = round(bitmath.MiB(bytes=int(file_info['format']['size'])).value, 2)
    click.echo('Length: {} , Size: {} MiB'.format(length, size))
    for stream in file_info['streams']:
        index = stream['index']
        stream_type = stream['codec_type']
        codec = stream['codec_name']
        language = stream['tags']['language'] if ('tags' in stream and 'language' in
            stream['tags']) else ''
        click.echo(click.style('  Stream {}: '.format(index), fg='yellow', bold=True)
            + click.style('{} {} {}'.format(codec, stream_type, language), fg='green'))
        if stream_type == 'video':
            resolution = str(stream['width']) + 'x' + str(stream['height'])
            bitrate = round(bitmath.Mib(bits=int(stream['bit_rate'])).value, 2)
            click.echo('    Resolution: {}, Bitrate: {} Mib/s'.format(resolution, bitrate))
        elif stream_type == 'audio':
            channels = stream['channel_layout']
            bitrate = round(bitmath.Kib(bits=int(stream['bit_rate'])).value, 2)
            click.echo('    Channels: {}, Bitrate: {} Kib/s'.format(channels, bitrate))


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
            display_file(file_info)


if __name__ == '__main__':
    cli(obj={})
