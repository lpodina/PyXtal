#!/bin/sh
sed -i -r 's/((\t|\s)+)except:/\1except TimeoutError:\n\1\traise\n\1except:/g' *.py
