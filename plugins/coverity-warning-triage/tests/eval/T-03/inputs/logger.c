#include <stdio.h>
#include <string.h>

/* ログを1行書く。書けなくても処理は続ける（ログは補助情報のため）。 */
void log_line(FILE *fp, const char *msg)
{
    fputs(msg, fp);
    fputc('\n', fp);
}

int copy_name(char *dst, size_t dst_size, const char *src)
{
    if (dst == NULL || src == NULL || dst_size == 0U) {
        return -1;
    }
    strcpy(dst, src);
    return 0;
}
