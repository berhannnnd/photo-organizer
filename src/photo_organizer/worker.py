"""Detached CLI worker entrypoint; durable orchestration lives in jobs.py."""
import argparse
from .jobs import run

def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--task',required=True)
    args=p.parse_args();run(args.state,args.task)

if __name__=='__main__':main()
