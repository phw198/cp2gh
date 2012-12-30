cp2gh
=====

Imports issues from CodePlex projects to a GitHub repo.

usage
=====
cp2gh [-vq] [--usermap=USERMAP] [--skipcp] [--count=COUNT] --ghuser=GHUSER --ghpass=GHPASS [--ghorg=GHORG] CPPROJECT GHREPO


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

  --count=COUNT     the number of issues to import (used mainly for testing)
