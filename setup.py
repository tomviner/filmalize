from setuptools import setup

setup(
    name='filmalize',
    version='0.0.1',
    py_modules=['filmalize'],
    install_requires=[
        'Click'
    ],
    entry_points='''
        [console_scripts]
        filmalize=filmalize:cli
    ''',
)
