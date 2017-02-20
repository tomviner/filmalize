"""A simple tool for converting video files.

System Dependencies:
    * ffmpeg

Todo:
    * Config File
    * Convert command
    * Filename whitelist?

"""

import os
import subprocess
import json

import click


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

@click.group()
@click.option('-f', '--file', type=click.Path(exists=True),
    help='Specify a file.')
@click.option('-d', '--directory', type=click.Path(exists=True),
    help='Specify a directory.')
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

    if file:
        ctx.obj['FILES'] = [file]
    else:
        directory = directory if directory else '.'
        if recursive:
            ctx.obj['FILES'] = [os.path.join(root, file) for root, dirs, files
                in os.walk(directory) for file in files]
        else:
            ctx.obj['FILES'] = [dir_entry.path for dir_entry in
                os.scandir(directory) if dir_entry.is_file()]

@cli.command()
@click.pass_context
def display(ctx):
    """Display information about video file(s)"""
    for file in ctx.obj['FILES']:
        probe_info = subprocess.run(['/usr/bin/ffprobe', '-v', 'error',
            '-show_format', '-show_streams', '-of', 'json', file],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if not probe_info.returncode:
            click.echo(json.loads(probe_info.stdout))
        else:
            click.echo('ffprobe warning - {}'.format(
                probe_info.stderr.decode('utf-8').strip('\n')))


@cli.command()
@click.pass_context
def convert(ctx):
    """Convert video file(s)"""
    click.echo('Convert File(s)')

if __name__ == '__main__':
    cli(obj={})
