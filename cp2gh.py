"""Usage: cp2gh [-vq] [--usermap=USERMAP] [--skipcp] [--skipclosed] [--count=COUNT] --ghuser=GHUSER --ghpass=GHPASS [--ghorg=GHORG] CPPROJECT GHREPO
          

Process FILE and optionally apply correction to either left-hand side or
right-hand side.

Arguments:
  CPPROJECT        the project name on CodePlex to port (e.g., http://PROJECTNAME.codeplex.com)
  GHREPO           the repo on GitHub to port to (https://github.com/owner/GHREPO)

Options:
  -h --help
  -v                verbose mode
  -q                quiet mode
  --ghuser=GHUSER   the username for GitHub authentication
  --ghpass=GHPASS   the password for GutHub authentication
  --ghorg=GHORG     the organization that owns the repo, if not specified, the GHUSER will be used as owner
  --usermap=USERMAP load a file which maps CodePlex users to GitHub users
  --skipcp          skip parsing data from CodePlex and use existing issues.db file
  --skipclosed     skip importing issues that are closed on CodePlex
  --count=COUNT     the number of issues to import (used mainly for testing)

"""

import sys
import os.path
import re
import pprint
import cPickle as pickle
import sqlite3
import datetime
import time
import mimetypes
import textwrap

from docopt import docopt

import urllib2
import bs4
import html2text
import github

def is_plain_text_file(filename):
    mime = mimetypes.guess_type(filename)
    if not mime[0]:
        parts = os.path.splitext(filename)
        ext = ''
        if len(parts) > 1:
            ext = parts[1]
        return ext.lower() not in ['.dll', '.dat', '.zip', '.exe', '.7z', '.png', '.jpg', '.jpeg', '.docx', '.doc', '.ppt', '.pptx', '.xls', '.xlsx', '.bmp', '.gif', '.rtf', '.swf', '.blg', '.rar']    
    else:
       return mime[0].startswith('text')

if __name__ == '__main__':
    options = docopt(__doc__)  # parse arguments based on docstring above
    CPPROJECT = options['CPPROJECT']
    GHREPO = options['GHREPO']
    username = options['--ghuser']
    password = options['--ghpass']
    org = options['--ghorg']
    skipcp = ('--skipcp' in options) and options['--skipcp']
    skip_closed = ('--skipclosed' in options) and options['--skipclosed']
    curPage = 0
    maxCount = -1
    if options['--count']:
        maxCount=int(options['--count'])

    issues = {}
    usermap = {}

    conn = sqlite3.connect('issues.db')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS issues (
                 ID INTEGER PRIMARY KEY NOT NULL,
                 Link TEXT NOT NULL,
                 Title TEXT NOT NULL,
                 Assignee TEXT DEFAULT NULL,
                 Status TEXT NOT NULL DEFAULT 'open',
                 Severity TEXT NOT NULL DEFAULT 'low',
                 Reporter TEXT DEFAULT '',
                 Description TEXT DEFAULT '',
                 LastUpdate INTEGER DEFAULT -1,
                 Updated INTEGER DEFAULT 0,
                 Done INTEGER DEFAULT 0,
                 GitHubIssueID INTEGER DEFAULT -1)""")

    c.execute("""CREATE TABLE IF NOT EXISTS comments (
                 IssueID INTEGER NOT NULL,
                 Date INTEGER NOT NULL,
                 User TEXT NOT NULL,
                 Link TEXT NOT NULL DEFAULT '',
                 Comment TEXT NOT NULL DEFAULT '',
                 FOREIGN KEY(IssueID) REFERENCES issues(ID) )""")

    c.execute("""CREATE TABLE IF NOT EXISTS attachments (
                 IssueID INTEGER NOT NULL,
                 LinkText TEXT NOT NULL,
                 Href TEXT NOT NULL,
                 FOREIGN KEY(IssueID) REFERENCES issues(ID) )""")

    c.execute("""CREATE TABLE IF NOT EXISTS issue_to_label (
                 IssueID INTEGER NOT NULL,
                 Label TEXT NOT NULL,
                 FOREIGN KEY(IssueID) REFERENCES issues(ID) )""")

    c.execute("""CREATE TABLE IF NOT EXISTS issue_to_milestone (
                 IssueID INTEGER NOT NULL,
                 Milestone TEXT NOT NULL,
                 FOREIGN KEY(IssueID) REFERENCES issues(ID) )""") 

    c.execute("""CREATE TABLE IF NOT EXISTS usermap (
                 CodePlexId TEXT UNIQUE NOT NULL,
                 GitHubId TEXT UNIQUE NOT NULL )""")

    c.execute("""CREATE TABLE IF NOT EXISTS issue_metadata (
                 IssueID INTEGER NOT NULL,
                 Name TEXT NOT NULL,
                 Value TEXT NOT NULL,
                 FOREIGN KEY(IssueID) REFERENCES issues(ID) )""")

    if options['--usermap']:
        with open(options['--usermap'], 'r') as f:
            for line in f:
                items = line.split('=')
                res = c.execute("INSERT OR REPLACE INTO usermap (CodePlexId, GitHubId) VALUES(?, ?)", (items[0].strip(), items[1].strip()))

    titleLinkRE = re.compile(r'TitleLink\d+')
    commentRE = re.compile('CommentContainer\d+')
    fileLinkRE = re.compile('FileLink\d+')    
    if not skipcp:
        while True:
            contentRead = False
            link = 'http://%s.codeplex.com/workitem/list/advanced?keyword=&status=All&type=All&priority=All&release=All&assignedTo=All&component=All&sortField=Id&sortDirection=Ascending&size=100&page=%d' % (CPPROJECT, curPage)
            while not contentRead:
                try:
                    request = urllib2.urlopen(link)
                    encoding = request.headers.getparam('charset')
                    content = request.read()
                    contentRead = True
                except urllib2.URLError:
                    print 'Error retrieving URL (%s)...waiting 10 seconds to try again' % link
                    time.sleep(10)
                except urllib2.HTTPError:
                    print 'HTTP error retrieving URL (%s)...waiting 10 seconds to try again' % link
                    time.sleep(10)
                except KeyboardInterrupt:
                    raw_input('Press enter to exit cp2gh')
                    sys.exit(-1)

            soup = bs4.BeautifulSoup(content.decode(encoding), 'html5lib')
            # if we're on the first page, let's get some info we'll use later
            if curPage == 0:
                itemsText = soup.find('ul', 'advanced_pagination').li.get_text()
                res = re.search(r'of (\d+) items', itemsText)
                totalItems = 0
                totalPages = 0
                if res:
                    totalItems = int(res.group(1))
                    totalPages = totalItems / 100
                    if totalItems % 100 > 0:
                        totalPages += 1

                #for component in [x['value'] for x in soup.find('select', id='ComponentListBox').find_all('option') if x['value'] != 'No Component Selected']:
                #    c.execute('SELECT * FROM labels WHERE Label=?', (component, ))
                #    if c.rowcount <= 0:
                #        c.execute('INSERT OR REPLACE INTO labels (Label) VALUES(?)', (component, ))            
                                            
                #for release in [x['value'] for x in soup.find('select', id='PlannedReleaseListBox').find_all('option') if x['value'] not in ['Unassigned', 'All']]:
                #    r= c.execute('SELECT * FROM milestones WHERE Milestone=?', (release, ))
                #    if not r:
                #        c.execute('INSERT OR REPLACE INTO milestones (Milestone) VALUES(?)', (release, ))                    
            
                if not totalItems:
                    print 'Could not parse item count from project issue tracker'
                else:
                    print 'Parsing %d issues from %d pages' % (totalItems, totalPages)
        
            print 'Parsing page ', curPage
            curPage += 1
            issueRows = soup.find_all('tr', id=re.compile(r'row_checkbox_\d+'))
            for issueRow in issueRows:            
                id = int(issueRow.find('td', 'ID').text)
                assignedTo = issueRow.find('td', 'AssignedTo').text.strip()
                updateDate = int(issueRow.find('span', 'smartDate')['localtimeticks'])
                c.execute("""INSERT OR REPLACE INTO issues (ID, Title, Link, Assignee, Status, LastUpdate, Updated) VALUES(?, ?, ?, ?, ?, ?, 1)""",
                          (id, issueRow.find('a', id=titleLinkRE).text, issueRow.find('a', id=titleLinkRE)['href'], assignedTo, issueRow.find('td', 'Status').text, updateDate))
                severity = issueRow.find('td', 'Severity').text.lower()
                if not len(severity.strip()):
                    severity = 'low'

                issueType = issueRow.find('td', 'Type').text.lower()
                if issueType == 'issue':
                    issueType = 'bug'
                elif issueType == 'feature':
                    issueType = 'enhancement'

                #c.execute('INSERT OR REPLACE INTO labels (Label) VALUES(?)', (severity, ))
                #c.execute('INSERT OR REPLACE INTO labels (Label) VALUES(?)', (issueType, ))
                c.execute('INSERT OR REPLACE INTO issue_to_label (IssueID, Label) VALUES(?, ?)', (id, severity))
                c.execute('INSERT OR REPLACE INTO issue_to_label (IssueID, Label) VALUES(?, ?)', (id, issueType))

            if curPage >= totalPages:
                break

        conn.commit()

        xml_fields = [ 'Test', 'ResolvedBy', 'Description', 'Repro', 'History', 'Creator', 'CreatedDate', 'NewInternalID', 'OldInternalID', 'AreaPath', 'Area', 'OpenBuild', 'Thanks']

        # we should have a list of issues now
        # so all we need to do is fill in the comments, description, and attachments    
        c.execute('SELECT ID, Link FROM issues WHERE Updated=1 ORDER BY ID')
        rows = c.fetchall()
        count = 0
        for row in rows:            
            id = row[0]
            link = row[1]

            print '%.2f%% - Parsing issue %d from %s' % ((count / (len(rows) * 1.0)) * 100, id, link)
            contentRead = False
            while not contentRead:
                try:
                    request = urllib2.urlopen(link)
                    encoding = request.headers.getparam('charset')
                    content = request.read()
                    contentRead = True
                except urllib2.URLError:
                    print 'Error retrieving URL (%s)...waiting 10 seconds to try again' % link
                    time.sleep(10)
                except urllib2.HTTPError:
                    print 'HTTP error retrieving URL (%s)...waiting 10 seconds to try again' % link
                    time.sleep(10)
                except KeyboardInterrupt:
                    raw_input('Press enter to exit cp2gh')
                    sys.exit(-1)

            soup = bs4.BeautifulSoup(content.decode(encoding), 'html.parser')

            component = soup.find('a', id='ComponentLink').text
            if component not in ['No Component Selected', 'All']:
                c.execute('INSERT OR REPLACE INTO issue_to_label (IssueID, Label) VALUES(?, ?)', (id, component.lower()))

            version = soup.find('a', id='ReleaseLink').text
            if version not in ['All', 'Unassigned']:
                c.execute('INSERT OR REPLACE INTO issue_to_milestone (IssueID, Milestone) VALUES(?, ?)', (id, version))

            reportedBy = soup.find('a', id='ReportedByLink').text.strip()
            updatedBy = None
            if not len(reportedBy):
                updatedBy = soup.find('a', id='UpdatedByLink').text.strip()
            else:
                c.execute('UPDATE issues SET Reporter=? WHERE ID=?', (reportedBy, id))

            comments = soup.find_all('div', id=commentRE)
            c.execute('DELETE FROM comments WHERE IssueId=?', (id, ))
            for comment in comments:
                authorInfo = comment.find('a', 'author')
                user = authorInfo.text
                userlink = authorInfo['href']
                date = int(comment.find('span', 'smartDate')['localtimeticks'])
                comment = comment.find('div', 'markDownOutput').text            
                c.execute('INSERT INTO comments (IssueID, Date, User, Link, Comment) VALUES(?, ?, ?, ?, ?)', (id, date, user, userlink, comment))

            itemDetails = soup.find('div', 'right_sidebar_table')
            for detailRow in itemDetails.find_all('tr'):
                h = html2text.HTML2Text()
                h.ignore_links = True

                left = detailRow.find('td', 'left')
                right = detailRow.find('td', 'right')
                leftitems = [x.replace(':', '').strip() for x in html2text.html2text(left.prettify()).split('\n') if x]
                rightitems = [x.replace('n/a', '').strip() for x in h.handle(right.prettify()).split('\n') if x]

                while len(rightitems) < len(leftitems):
                    rightitems.append('')
                for (name, value) in zip(leftitems, rightitems):
                    if len(value) and name not in ['Type', 'Item number', 'User comments', 'Impact', 'Release', 'Component']:
                        c.execute('INSERT OR REPLACE INTO issue_metadata (IssueID, Name, Value) VALUES(?, ?, ?)', (id, name, value))                

            # check the description for XML fields and update the meta data from that information
            description = html2text.html2text(soup.find('div', id='descriptionContent').prettify())
            for xml_field in xml_fields:
                replaceAll = True
                xml_start_tag = '<' + xml_field + '>'
                xml_end_tag = '</' + xml_field + '>'
                if description.find(xml_start_tag) >= 0:
                    value = description[description.find(xml_start_tag) + len(xml_start_tag):description.find(xml_end_tag)].strip()
                    fullTag = description[description.find(xml_start_tag):description.find(xml_end_tag) + len(xml_end_tag) + 1].strip()
                    if len(value):
                        if xml_field in ['Description', 'History', 'Repro']:
                            replaceAll = False
                            description = description.replace(xml_start_tag, '').replace(xml_end_tag, '')
                        elif xml_field in ['ReportedBy', 'Creator']:
                            reportedBy = value
                            c.execute('UPDATE issues SET Reporter=? WHERE ID=?', (value, id))                            
                        else:
                            c.execute('INSERT INTO issue_metadata (IssueID, Name, Value) VALUES(?, ?, ?)', (id, xml_field, value))
                    if replaceAll:
                        description = description.replace(fullTag, '')                            
        
            description = description.lstrip()

            description += 'Work Item Details\n--------------------\n'
            description += '**Original CodePlex Issue:**\t[Issue %d](%s)\n' % (id, link)            
            c.execute('SELECT Name, Value FROM issue_metadata WHERE IssueID=?', (id, ))
            for metadata in c.fetchall():
                description += '**%s:**\t%s\n' % (metadata[0], metadata[1])

            c.execute('UPDATE issues SET description=? WHERE ID=?', (description, id))

            attachments = soup.find_all('a', id=fileLinkRE)
            c.execute('DELETE FROM attachments WHERE IssueID=?', (id, ))
            for attachment in attachments:
                c.execute('INSERT INTO attachments (IssueID, LinkText, Href) VALUES(?, ?, ?)', (id, attachment.text, 'http://%s.codeplex.com%s' % (CPPROJECT, attachment['href'])))            

            count += 1
        conn.commit()

    raw_input('Please press any key to continue to import the issues to GitHub...')
    
    count = 0
    gh = github.Github(username, password)
    user = gh.get_user()
    if org:
        repo = gh.get_organization(org).get_repo(GHREPO)
    else:
        if '/' in GHREPO:
            (owner, GHREPO) = GHREPO.split('/')
            owner = gh.get_user(owner)
            repo = owner.get_repo(GHREPO)
        else:
            repo = user.get_repo(GHREPO)
    
    if not repo:
        print 'Unable to access %s as user %s' % (GHREPO, username)
        sys.exit(-1)
    else:
        print 'Authenticated for %s as user %s' % (GHREPO, username)

    labels = { 'low' : '5BB13D', 'medium' : 'E36B23', 'high' : 'E10C02', 'task' : '4183C4' }
    existingLabels = [x.name for x in repo.get_labels()]
    for l in labels:
        if l not in existingLabels:
            repo.create_label(l, labels[l])
            existingLabels.append(l)

    collaborators = [x.login for x in repo.get_collaborators()]

    existingMilestones = {x.title : x.number for x in repo.get_milestones()}
    existingMilestones.update({x.title : x.number for x in repo.get_milestones(state='closed')})
    c.execute('SELECT ID, Title, Description, Status, Assignee FROM issues WHERE Done=0 ORDER BY ID')
    rows = c.fetchall()
    for row in rows:
        if maxCount > 0 and count >= maxCount:
            break

        if row[3] == 'Closed' and skip_closed:
            continue

        print '%.2f%% - Importing issue %d to GitHub repo %s' % ((count / (len(rows) * 1.0)) * 100, row[0], repo.name)
        if gh.rate_limiting[0] < 100:
            print 'WARNING: GitHub API rate limit approaching soon (100 requests left)!'

        if gh.rate_limiting[0] == 0:
            print 'ERROR: GitHub API rate limit exceeded!'
            sys.exit(-1)

        body = row[2]
        assignee = github.GithubObject.NotSet
        if row[4]:
            c.execute('SELECT GitHubId FROM usermap WHERE CodePlexId=?', (row[4], ))
            u = c.fetchone()
            if u:
                assignee = gh.get_user(u[0])
                if isinstance(assignee, github.NamedUser.NamedUser) and assignee.login not in collaborators:
                    assignee = github.GithubObject.NotSet
                    #repo.add_to_collaborators(assignee)
                    #existingCollaborators.append(assignee.login)

        c.execute('SELECT LinkText, Href FROM attachments WHERE IssueID=?', (row[0], ))

        attachments = c.fetchall()
        plaintext_attachments = [x for x in attachments if is_plain_text_file(x[0])]
        binary_attachments = [x for x in attachments if not is_plain_text_file(x[0])]

        gist_files = {}
        for attachment in plaintext_attachments:
            # create gist and link to that instead...
            req = urllib2.urlopen(attachment[1])
            encoding = req.headers.getparam('charset')
            contentOrig = req.read()
            if not encoding:                
                encodings = ['utf8', 'cp1252']
                for encoding in encodings:
                    try:
                        content = contentOrig.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        content = contentOrig
            else:
                content = contentOrig.decode(encoding)
            
            gist_files[attachment[0]] = github.InputFileContent(content)
            
        continuations = []
        if len(body) >= (60*1024):
            continuations = textwrap.wrap(body, 60*1024)      
            body = continuations.pop(0)              

        if gist_files:
            g = user.create_gist(True, gist_files, 'CodePlex Issue #%d Plain Text Attachments' % row[0])
            body += '\n\n#### Plaintext Attachments\n\n[%s](%s)' % (g.description, g.html_url)            

        if binary_attachments:
            body += '\n\n#### Binary Attachments\n\n'
        for attachment in binary_attachments:
            # best we can do is put in a link to the original attachment on CodePlex...            
            body += '[%s](%s)' % (attachment[0], attachment[1])

        ghIssue = repo.create_issue(row[1], body=body, assignee=assignee)

        if continuations:
            for comment in continuations:
                ghIssue.create_comment(comment)

        #if isinstance(assignee, github.NamedUser.NamedUser):
        #    repo.remove_from_collaborators(assignee)

        c.execute('SELECT Date, User, Link, Comment, IssueID FROM comments WHERE IssueID=? ORDER BY Date ASC', (row[0], ))
        for comment in sorted(c.fetchall(), cmp=lambda x, y: cmp(x[0], y[0])):
            commentDate = time.gmtime(comment[0])[:6]
            commentDate = datetime.datetime(*commentDate)
            commentor = comment[1].strip()
            if commentor in ['', u'']:
                commentor = 'unknown user'
            ghIssue.create_comment('On *%s*, **%s** commented:\n\n%s' % (commentDate.strftime('%Y-%m-%d %H:%M:%S UTC'), commentor, comment[3]))
            time.sleep(2)    

        m = c.execute('SELECT Milestone FROM issue_to_milestone WHERE IssueID=?', (row[0], )).fetchone()
        parameters = {}
        if m:
            if m[0] in existingMilestones.keys():
                parameters['milestone'] = repo.get_milestone(existingMilestones[m[0]])
            else:
                milestone = repo.create_milestone(m[0])
                existingMilestones[milestone.title] = milestone.number
                parameters['milestone'] = milestone

        c.execute('SELECT Label FROM issue_to_label WHERE IssueID=?', (row[0], ))
        for label in c.fetchall():
            if 'labels' not in parameters:
                parameters['labels'] = []

            if len(label[0]):
                if (label[0] not in existingLabels):
                    l = repo.create_label(label[0], '000000')
                    parameters['labels'].append(l.name)
                    existingLabels.append(l.name)
                else:
                    parameters['labels'].append(label[0])

        if row[3] == 'Closed':
            parameters['state'] = 'closed'
            
        # update the issue with the information
        ghIssue.edit(**parameters)

        c.execute('UPDATE issues SET Done=1, Updated=0, GitHubIssueID=? WHERE ID=?', (ghIssue.id, row[0]))
        conn.commit()

        count += 1
        
    raw_input('Press enter to continue...')
