Quickstart
==========

Installing
----------

Clone the repo
              

::

    $ git clone https://github.com/thebopshoobop/filmalize.git

Initialize and source a virtualenv
                                  

::

    $ cd filmalize
    $ virtualenv -p python3 venv
    $ source venv/bin/activate

Install dependencies, generate script, profit
                                             

::

    (venv) $ pip install -r requirements.txt
    (venv) $ pip install --editable .

Running
-------

You can just run it in the virtualenv for testing and whatnot:
                                                              

::

    (venv) $ filmalize display

Or link it into your path for easy access:
                                          

::

    $ ln -s /path/to/filmalize/venv/bin/filmalize /somewhere/in/your/path/filmalize
    $ filmalize -r convert

Using
-----

filmalize has two commands: display and convert, which display a pretty
representation of or convert your file(s), respectively. By default it
attempts to do the specified action to all of the files in the current
directory. However, you can specify a particular file or directory, or
enable recursive execution by including the appropriate flags before the
command. Check out ``$ filmalize --help`` for details. If you decide to
convert, filmalize will generate a default set of actions for each file,
and allow you to adjust the output through a keyboard-driven menu. When
instructed to convert a file, filmalize starts a new process in the
background to perform the processing and continues to the next file to
configure. Once all of the conversions have been started, filmalize
displays progress bars and an eta countdown timer to comfort you while you
wait.
