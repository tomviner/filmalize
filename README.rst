Introduction
------------

Named a `portmanteau word`_ composed of *film* and *standardize*,
filmalize is a tool for standardizing a video library. filmalize is
built with `Click`_ for python 3.4+ and also depends on the `bitmath`_,
`chardet`_, `blessed`_, and `progressbar2`_ libraries. filmalize uses
`ffmpeg`_ for all of the actual probing and converting.

I plan to expand it to produce other container formats, but at the
moment filmalize is set up to produce `mp4`_ containers, with `h264`_
video, `aac`_ audio, and `mov_text`_ subtitle streams. I chose these
parameters since I wrote filmalize to prepare videos for a site that
uses `flowplayer`_, and this combination allows for maximal end-user
compatibility in a single file format.

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

.. _portmanteau word: https://en.wikipedia.org/wiki/Portmanteau
.. _Click: http://click.pocoo.org/6/
.. _bitmath: http://bitmath.readthedocs.io/en/latest/
.. _chardet: http://chardet.readthedocs.io/en/latest/
.. _ffmpeg: https://www.ffmpeg.org/
.. _mp4: https://en.wikipedia.org/wiki/MPEG-4_Part_14
.. _h264: https://en.wikipedia.org/wiki/H.264/MP
.. _aac: https://en.wikipedia.org/wiki/Advanced_Audio_Coding
.. _mov_text: https://en.wikibooks.org/wiki/FFMPEG_An_Intermediate_Guide/subtitle_options#Set_Subtitle_Codec
.. _flowplayer: https://flowplayer.org/docs/setup.html#video-formats
.. _blessed: http://blessed.readthedocs.io/en/latest/
.. _progressbar2: http://progressbar-2.readthedocs.io/en/latest/
