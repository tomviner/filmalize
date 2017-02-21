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

    for stream in file_info['streams']:
        stream_header = []
        if 'index' in stream:
            stream_header.append('Stream {}:'.format(stream['index']))
        stream_info = []
        if 'codec_type' in stream:
            stream_type = stream['codec_type']
            stream_info.append(stream_type)
        if 'codec_name' in stream:
            stream_info.append(stream['codec_name'])
        if 'tags' in stream and 'language' in stream['tags']:
            stream_info.append(stream['tags']['language'])
        if 'disposition' in stream and 'default' in stream['disposition']:
            if stream['disposition']['default']:
                stream_info.append('default')
        click.echo('  ' + click.style(' '.join(stream_header), fg='green', bold=True) + ' '
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
            if 'field_order' in stream:
                stream_specs.append('Scan: {}'.format(stream['field_order']))
        elif stream_type == 'audio':
            if 'channel_layout' in stream:
                stream_specs.append('Channels: {}'.format(stream['channel_layout']))
            if 'bit_rate' in stream:
                bitrate = round(bitmath.Kib(bits=int(stream['bit_rate'])).value)
                stream_specs.append('Bitrate: {}Kib/s'.format(bitrate))
        if stream_specs:
            click.echo('    ' + ' | '.join(stream_specs))


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
