import argparse
from database.db import get_conn


PLACEHOLDER_DOMAINS = ('example.com', 'example.org', 'example.net', 'test.com', 'localhost')


def matching_jobs(cur):
    cur.execute(
        "SELECT id, employer, job_title, source, job_url FROM jobs "
        "WHERE source='test' AND (job_url LIKE '%example.com%' OR job_url LIKE '%example.org%' "
        "OR job_url LIKE '%example.net%' OR job_url LIKE '%test.com%' OR job_url LIKE '%localhost%')"
    )
    return cur.fetchall()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm', action='store_true', required=True)
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Confirmation required (--confirm)")

    conn = get_conn()
    cur = conn.cursor()
    try:
        rows = matching_jobs(cur)
        print(f"Matching test records: {len(rows)}")
        for r in rows:
            print(f"  id={r['id']} employer={r['employer']} title={r['job_title']} source={r['source']} url={r['job_url']}")

        if not rows:
            conn.close()
            return

        ids = [r['id'] for r in rows]
        placeholders = ','.join('?' for _ in ids)
        cur.execute(f"SELECT COUNT(*) AS c FROM applications WHERE job_id IN ({placeholders})", ids)
        linked = cur.fetchone()['c']
        if linked:
            print(f"Refusing deletion: {linked} application record(s) reference these jobs.")
            conn.close()
            return

        cur.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", ids)
        deleted = cur.rowcount
        conn.commit()
        print(f"Deleted {deleted} test job record(s).")
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
