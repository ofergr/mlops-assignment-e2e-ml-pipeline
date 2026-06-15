Hi my MLOps colleague,

So, I managed to run this `mini-swe-agent` on a VM with Docker. BTW, I checked the source code [github.com/SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), it's really simple, close to 100 lines of code -- don't hestitate to check it out yourself / ask Codex to explain it to you. I've never thought that these coding agents are sooo simple in a nutshell!

Check my script `mini-swe-agent-bench-single.sh` -- it runs `mini-swe-agent` on a single SWE-bench instance. It uses `Qwen/Qwen3-30B-A3B-Instruct-2507`, make sure to set your `NEBIUS_API_KEY`.

Try it yourself, see how it works. Once it completes, you should find `trajectory.json` file with all of the steps, agent configuration, patch, etc.

`trajectory.json` could be hard to read by eye, this tool could help: `mini-e inspect trajectory.json`.
