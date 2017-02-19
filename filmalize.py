import click

@click.group()
def cli():
    """A simple tool for converting video files.

    By default filmalize operates on all files in the current directory. If
    necessary, you may specify an individual file or a different working
    directory. For more information please see filmalize.py COMMAND --help."""
    pass

@cli.command()
@click.option('-f', '--file', type=click.Path(exists=True), help='specify a file')
@click.option('-d', '--directory', type=click.Path(exists=True), help='specify a directory')
@click.option('-r', '--recursive', default=False, is_flag=True, help='operate recursively')
def display(file, directory, recursive):
    """Display information about video files"""
    click.echo('Display Info')

@cli.command()
@click.option('-f', '--file', type=click.Path(exists=True), help='specify a file')
@click.option('-d', '--directory', type=click.Path(exists=True), help='specify a directory')
@click.option('-r', '--recursive', default=False, is_flag=True, help='operate recursively')
def convert(file, directory, recursive):
    """Convert video files"""
    click.echo('Convert File(s)')

if __name__ == '__main__':
    cli()
