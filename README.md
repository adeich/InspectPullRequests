InspectPullRequests
===================

This is a command line utility which calls the GitHub API and inspects a project's pull requests, looking for those which contain words and files of interest.

This program uses the `grequests` module for concurrent web requests. You can download `grequests` using `pip`:

    $ sudo pip install grerequests


An example usage of `InspectPullRequests.py`, with username `puppetlabs` and project `puppet`:

    $ python InspectPullRequests.py puppetlabs puppet

