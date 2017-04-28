from setuptools import setup

setup(
    name='filmalize',
    version='0.0.1',
    packages=['filmalize'],
    include_package_data=True,
    install_requires=[
        'click', 'bitmath', 'colorama', 'chardet'
    ],
    entry_points='''
        [console_scripts]
        filmalize=filmalize.cli:cli
    ''',
)
