"""Command-Line Interface for filmalize."""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
import progressbar
import blessed

from filmalize.errors import (ProbeError, NoProgressError,
                              ProgressFinishedError)
from filmalize.models import Container
from filmalize.menus import main_menu, display_container


# Allow help to be called with '-h' as well as the default '--help'.
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


class Writer(object):
    """An object with a write method that writes to a specific line on the
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
                   progressbar.Bar(), progressbar.ETA()]
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
    err = ErrorWriter(terminal)
    pr_bar = build_progress_bars(running, terminal)

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
    click.clear()
    for message in err.messages:
        click.secho(message, fg='red', bg='black', )


if __name__ == '__main__':
    cli()
