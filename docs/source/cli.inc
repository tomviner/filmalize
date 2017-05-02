.. function:: cli.cli(ctx, file, directory, recursive)

    The :obj:`click.Group` that is the core of the cli.

    By default filmalize operates on all files in the current directory. If
    desired, you may specify an individual file or a different working
    directory. Directory operation may be recursive. A command (:obj:`display`
    or :obj:`convert`) is required.

    The :obj:`exclusive` function is used to ensure that the file and directory
    or file and recursive parameters cannot by passed simultaneously.

    Depending on the options passed, assign a :obj:`list` of :obj:`str` file
    names to the user context object :obj:`click.Context.obj`.

    :param ctx: The :obj:`click.Context` instance for this execution of the
        command
    :type ctx: :obj:`click.Context`
    :param file: The file on which to operate.
    :type file: :obj:`click.Path`, optional
    :param directory: The directory on which to operate.
    :type directory: :obj:`click.Path`, optional
    :param recursive: Flag to initiate recursive directory processing.
    :type  recursive: :obj:`bool`


.. function:: cli.display(ctx)

    The :obj:`click.Command` to display information about multimedia files.

    Take the list of filenames stored in :obj:`click.Context.obj`, use
    :obj:`build_contaners` to create an :obj:`list` of :obj:`Container`
    instances, and display those instances with :obj:`display_contianer`.

    :param ctx: The :obj:`click.Context` instance for this execution of the
        command

.. function:: cli.convert(ctx)

    The :obj:`click.Command` to convert multimedia files.

    Take the list of filenames stored in :obj:`click.Context.obj`, use
    :obj:`build_contaners` to create an :obj:`list` of :obj:`Container`
    instances. Those instances are displayed for consideration to the user
    using :obj:`menus.main_menu`, which passes back a list of the instances that the
    user has started. Finally, an informative display, which uses
    :obj:`progressbar.bar.ProgressBar` instances for each :obj:`Container` on a 
    :obj:`blessed.terminal.Terminal`, is shown to the user until the
    transcoding process has finished.

    :param ctx: The :obj:`click.Context` instance for this execution of the
        command
