"""Fetch pinned LocalVQE source, GGML submodule and checksum-verified models."""
import hashlib,json,shutil,subprocess,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];lock=json.loads((ROOT/'neural.lock.json').read_text())
source=ROOT/'vendor/localvqe-source';runtime=ROOT/'vendor/neural';runtime.mkdir(exist_ok=True)
def git(*args):return subprocess.check_output(['git',*map(str,args)],text=True).strip()
if not source.exists():
    subprocess.run(['git','clone','--no-checkout',lock['repository'],str(source)],check=True)
    git('-C',source,'checkout','--detach',lock['commit'])
if git('-C',source,'rev-parse','HEAD')!=lock['commit']:raise RuntimeError('Unexpected LocalVQE source revision')
git('-C',source,'submodule','update','--init','--recursive')
if git('-C',source/'ggml/vendor/ggml','rev-parse','HEAD')!=lock['ggml_commit']:raise RuntimeError('Unexpected GGML revision')
# Single AVX2 CPU backend. The app already requires AVX2; avoid extra ISA DLLs.
path=source/'ggml/CMakeLists.txt';text=path.read_text(encoding='utf-8')
text=text.replace('set(GGML_BACKEND_DL ON CACHE BOOL "" FORCE)','set(GGML_BACKEND_DL OFF CACHE BOOL "" FORCE)').replace('set(GGML_CPU_ALL_VARIANTS ON CACHE BOOL "" FORCE)','set(GGML_CPU_ALL_VARIANTS OFF CACHE BOOL "" FORCE)')
path.write_text(text,encoding='utf-8')
# Keep the backend JSON control channel free of native model-load diagnostics.
path=source/'ggml/localvqe_graph.cpp';text=path.read_text(encoding='utf-8').replace('printf("Graph model:', 'fprintf(stderr, "Graph model:');path.write_text(text,encoding='utf-8')
# Reuse inference workers. GGML otherwise creates a disposable pool per graph,
# which produced rare 30+ ms stalls in paced playback under CPU load.
path=source/'ggml/localvqe_graph.h';text=path.read_text(encoding='utf-8')
if 'cpu_threadpool_free' not in text:
    text=text.replace('    ggml_backend_t backend = nullptr;', '    ggml_backend_t backend = nullptr;\n    struct ggml_threadpool* cpu_threadpool = nullptr;\n    void (*cpu_threadpool_free)(struct ggml_threadpool*) = nullptr;')
path.write_text(text,encoding='utf-8')
path=source/'ggml/localvqe_graph.cpp';text=path.read_text(encoding='utf-8')
if '// Clear Mic persistent inference pool.' not in text:
    text=text.replace('    if (fn) fn(model.backend, n_threads);', '''    if (fn) fn(model.backend, n_threads);
    // Clear Mic persistent inference pool. Above-normal audio work; no idle polling.
    if (std::strcmp(backend_name, "CPU") == 0) {
        using new_fn = struct ggml_threadpool* (*)(struct ggml_threadpool_params*);
        using free_fn = void (*)(struct ggml_threadpool*);
        using set_fn = void (*)(ggml_backend_t, struct ggml_threadpool*);
        auto make_pool = reinterpret_cast<new_fn>(ggml_backend_reg_get_proc_address(reg, "ggml_threadpool_new"));
        auto free_pool = reinterpret_cast<free_fn>(ggml_backend_reg_get_proc_address(reg, "ggml_threadpool_free"));
        auto set_pool = reinterpret_cast<set_fn>(ggml_backend_reg_get_proc_address(reg, "ggml_backend_cpu_set_threadpool"));
        if (!make_pool || !free_pool || !set_pool) return fail();
        auto params = ggml_threadpool_params_default(n_threads);
        params.poll = 0;
        model.cpu_threadpool = make_pool(&params);
        model.cpu_threadpool_free = free_pool;
        if (!model.cpu_threadpool) return fail();
        set_pool(model.backend, model.cpu_threadpool);
    }''')
    text=text.replace('void free_graph_model(dvqe_graph_model& model) {', '''void free_graph_model(dvqe_graph_model& model) {
    if (model.cpu_threadpool) {
        model.cpu_threadpool_free(model.cpu_threadpool);
        model.cpu_threadpool = nullptr;
        model.cpu_threadpool_free = nullptr;
    }''')
path.write_text(text,encoding='utf-8')
# Prefer audio work over ordinary CPU-heavy jobs without realtime priority.
# Preserve any higher priority already assigned by PortAudio/MMCSS.
if 'params.prio = GGML_SCHED_PRIO_MEDIUM;' not in text:
    text=text.replace('        params.poll = 0;', '        params.poll = 0;\n        params.prio = GGML_SCHED_PRIO_MEDIUM;')
    path.write_text(text,encoding='utf-8')
path=source/'ggml/vendor/ggml/src/ggml-cpu/ggml-cpu.c';text=path.read_text(encoding='utf-8')
if '// Clear Mic: preserve an existing higher audio-thread priority.' not in text:
    text=text.replace('    if (!SetThreadPriority(GetCurrentThread(), p)) {', '''    // Clear Mic: preserve an existing higher audio-thread priority.
    if (prio == GGML_SCHED_PRIO_MEDIUM && GetThreadPriority(GetCurrentThread()) >= (int)p) return true;
    if (!SetThreadPriority(GetCurrentThread(), p)) {''')
path.write_text(text,encoding='utf-8')
for name,digest in lock['models'].items():
    path=runtime/name
    if not path.exists():
        data=urllib.request.urlopen('https://huggingface.co/LocalAI-io/LocalVQE/resolve/main/'+name,timeout=90).read()
        if hashlib.sha256(data).hexdigest()!=digest:raise RuntimeError('Neural model checksum mismatch')
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise RuntimeError('Modified neural model: '+name)
for name,file in [('LocalVQE',source/'LICENSE'),('ggml',source/'ggml/vendor/ggml/LICENSE')]:
    target=ROOT/'THIRD_PARTY'/name;target.mkdir(exist_ok=True);shutil.copy2(file,target/'LICENSE')
    (target/'SOURCE.txt').write_text(f"{lock['repository']}\nLocalVQE {lock['commit']}\nGGML {lock['ggml_commit']}\nCPU AVX2; native diagnostics redirected to stderr; persistent above-normal CPU worker pools with no idle polling; preserve higher audio-thread priority. Models: neural.lock.json\n",encoding='utf-8')
print('Neural sources, model checksums and licenses verified.')
