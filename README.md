This bot connects to both Hipchat and IRC. It connects a Hipchat room to an IRC channel so that any messages sent in either environment appear in the other.

The following settings should be set in the environment that runs the bot:

    export WILL_USERNAME='12345_6789012@chat.hipchat.com'
    export WILL_PASSWORD='FILL ME IN'
    export WILL_V2_TOKEN=''
    export WILL_ROOMS='IRC Code;IRC General'  # Any rooms you wish to connect to IRC must appear in this semi-colon separated list of Hipchat rooms
    export WILL_NAME='IRC'    # Must be the *exact, case-sensitive* full name from hipchat.
    export WILL_HANDLE='IRC'  # Must be the exact handle from hipchat.
    export WILL_REDIS_URL="redis://redis:6379"

To connect a Hipchat room to an IRC channel, open the room you wish to connect in hipchat and issue the command:

    @IRC connect to irc channel irc://NICKNAME@IRCSERVER/CHANNEL

You should change NICKNAME to the name you would like the bot to have on IRC. You should also replace the IRCSERVER and CHANNEL name in the above URL.
