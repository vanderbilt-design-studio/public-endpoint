#!/bin/bash
SIGNAL=INT
DURATION=10
timeout -s $SIGNAL $DURATION python main.py
if [ $? -eq 124 ]
then
    echo 'Success! Program timed out (meaning it ran for the full duration), exiting with code 0'
    exit 0
else
    echo 'Program may have failed, exiting with program status'
    exit $?
fi
