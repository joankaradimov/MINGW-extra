/* Upstream's examples/search.c, reading the pacman.conf named on the command
 * line: a native build cannot open /etc/pacman.conf. Searches every sync
 * database through the library and prints one line per match,
 * "<i|n> <db> <name> <version>", where i marks an installed package. */
#include <stdio.h>
#include <alpm.h>
#include <alpm_list.h>
#include <alpm_octopi_utils.h>

int main(int argc, char **argv)
{
	if (argc != 2) {
		fputs("usage: test-search <pacman.conf>\n", stderr);
		return 2;
	}

	AlpmUtils *utils = alpm_utils_new(argv[1]);
	alpm_list_t *found = alpm_utils_search_all_dbs(utils, "\\S");
	size_t count = 0;

	for (alpm_list_t *i = found; i; i = alpm_list_next(i), count++) {
		alpm_pkg_t *pkg = i->data;
		const char *name = alpm_pkg_get_name(pkg);
		printf("%s %s %s %s\n",
		       alpm_utils_get_installed_pkg(utils, name) ? "i" : "n",
		       alpm_db_get_name(alpm_pkg_get_db(pkg)), name,
		       alpm_pkg_get_version(pkg));
	}

	fprintf(stderr, "%zu packages found\n", count);
	alpm_utils_free(utils);
	return count ? 0 : 1;
}
