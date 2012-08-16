#!/usr/bin/env python
# coding=utf-8
#
#Copyright (c) 2011, Víctor R. Ruiz <rvr@linotipo.es>
#All rights reserved.
#
#Redistribution and use in source and binary forms, with or without
#modification, are permitted provided that the following conditions
#are met:
#
#1. Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#2. Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
#3. Neither the name of the author nor the names of its contributors
#   may be used to endorse or promote products derived from this software
#   without specific prior written permission.
#
#THIS SOFTWARE IS PROVIDED ''AS IS'' AND ANY EXPRESS OR IMPLIED
#WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
#MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN
#NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
#INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
#NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
#USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
#ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
#THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from gi.repository import Gtk, WebKit
import json
import urllib
import urlparse
import pycurl
import StringIO

AUTH_URL = 'https://www.facebook.com/dialog/oauth?client_id=%s&redirect_uri=%s&response_type=token&scope=%s'
PUBLISH_URL = "https://graph.facebook.com/me/feed"

class FacebookHelper:
    """ Creates a web browser using GTK+ and WebKit to authorize a
        desktop application in Facebook. It uses OAuth 2.0.
        Requires the Facebook's Application ID. The token is then
        saved to FB_TOKEN_FILE.
    """

    def __init__(self, token_file, app_key='368780939859975', scope='publish_stream'):
        """ Constructor. Creates the GTK+ app and adds the WebKit widget
            @param app_key Application key ID (Public).

            @param scope A string list of permissions to ask for. More at
            http://developers.facebook.com/docs/reference/api/permissions/
        """
        self.app_key = app_key
        self.token_file = token_file
        self.scope = scope

        self.load_token()

    def authorize(self, on_success=None, on_failure=None):
        print "Authorizing"

        self.token = ''
        self.token_expire = ''

        # Creates the GTK+ app
        self.window = Gtk.Window()
        self.scrolled_window = Gtk.ScrolledWindow()

        # Creates a WebKit view
        self.web_view = WebKit.WebView()
        self.scrolled_window.add(self.web_view)
        self.window.add(self.scrolled_window)

        # Connects events

        def destroy_event_cb(widget):
            self._destroy_event_cb(widget, on_failure=on_failure)

        self.window.connect('destroy', destroy_event_cb) # Close window

        def load_committed_cb(web_view, frame):
            self._load_committed_cb(web_view, frame, on_success=on_success)

        self.web_view.connect('load-committed', load_committed_cb) # Load page

        self.window.set_default_size(1024, 800)
        # Loads the Facebook OAuth page
        self.web_view.load_uri(
            AUTH_URL % (
                urllib.quote(self.app_key),
                urllib.quote('https://www.facebook.com/connect/login_success.html'),
                urllib.quote(self.scope))
            )

    def _load_committed_cb(self, web_view, frame, on_success):
        """ Callback. The page is about to be loaded. This event is captured
            to intercept the OAuth 2.0 redirection, which includes the
            access token.

            @param web_view A reference to the current WebKitWebView.

            @param frame A reference to the main WebKitWebFrame.
        """
        # Gets the current URL to check whether is the one of the redirection
        uri = frame.get_uri()
        parse = urlparse.urlparse(uri)
        if (hasattr(parse, 'netloc') and hasattr(parse, 'path') and
            hasattr(parse, 'fragment') and parse.netloc == 'www.facebook.com' and
            parse.path == '/connect/login_success.html' and parse.fragment):
            # Get token from URL
            params = urlparse.parse_qs(parse.fragment)
            self.token = params['access_token'][0]
            self.token_expire = params['expires_in'][0] # Should be equal to 0, don't expire
            # Save token to file
            with open(self.token_file, 'w') as token_file:
                token_file.write(self.token)
                token_file.close()
            self.window.destroy()
            if on_success:
                on_success(self, self.token)
        else:
            self.window.show_all()

    def _destroy_event_cb(self, widget, on_failure):
        self.window.destroy()
        if not self.token and on_failure:
            on_failure(self, "authorize", "Login window closed before authorization")

    def load_token(self):
        print "Loading token from file"
        try:
            with open(self.token_file, 'r') as token_file:
                self.token = token_file.read().strip()
        except Exception:
            self.token = ''

    def publish(self, message=None, link=None, picture=None, on_success=None, on_failure=None, attempts=0):
        def republish(action, token):
            self.publish(message, link, picture, on_success, on_failure, attempts + 1)

        print "Publishing to Faceboook, %d" % attempts
        if not self.token:
            print "No auth token, loading from file"
            self.load_token()

        if not self.token:
            print "Still no token, trying to authorize"
            self.authorize(on_success=republish, on_failure=on_failure)
            return

        # now we certainly have some token, but it may be expired or invalid
        m = {"access_token": self.token}
        if message: m["message"] = message
        if link: m["link"] = link
        if picture: m["picture"] = picture

        try:
            content = FacebookHelper.post(PUBLISH_URL, m)
        except pycurl.error, e:
            on_failure(self, "publish", str(e))
            return

        response = json.loads(content)

        print response

        if "error" in response:
            code = response["error"]["code"]
            if attempts < 2 and code in [190, 200]: # 190 is invalid token, 200 means no permission to publish
                print "Trying to reauthorize"
                self.authorize(on_success=republish, on_failure=on_failure)
                return
            else:
                on_failure(self, "publish", response["error"]["message"])
        else:
            if on_success:
                on_success(self, "publish", content)

    @staticmethod
    def post(url, post_data):
        c = pycurl.Curl()
        c.setopt(pycurl.URL, url)
        c.setopt(pycurl.POST, 1)
        c.setopt(pycurl.POSTFIELDS, urllib.urlencode(post_data))
        b = StringIO.StringIO()
        c.setopt(pycurl.WRITEFUNCTION, b.write)
        c.perform()
        c.close()
        return b.getvalue()

if __name__ == '__main__':
    def success(browser, token):
        print "Token: %s" % token
        browser.authorize()

        #Gtk.main_quit()

    def cancel(browser):
        print "Pity."
        Gtk.main_quit()

    browser = FacebookHelper(app_key='368780939859975', token_file=".fbtoken", scope='publish_stream')
    def on_success(browser, action, data): print "Published"; Gtk.main_quit()
    def on_failure(browser, action, error): print "Pity"; Gtk.main_quit()
    browser.publish(message="Testing something, ignore", link="http://google.com",
                    on_success=on_success,
                    on_failure=on_failure)
    Gtk.main()
