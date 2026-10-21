"""Auditable, fail-closed compatibility patches for the exact MADlib 2.1.0 source."""

from pathlib import Path


def replace_once(path, before, after):
    source = Path(path).read_text()
    if source.count(before) != 1:
        raise RuntimeError(f"Unexpected upstream source in {path}")
    Path(path).write_text(source.replace(before, after))


# MADlib overrides local new/delete with palloc/pfree. libstdc++'s new string ABI
# can allocate in out-of-line stream code and destroy via MADlib's local delete.
# Retain C++11 language support but use the supported libstdc++ legacy string ABI.
replace_once(
    "CMakeLists.txt",
    'add_definitions("-D_GLIBCXX_USE_CXX11_ABI=1")',
    'add_definitions("-D_GLIBCXX_USE_CXX11_ABI=0")',
)
for filename in (
    "src/ports/postgres/dbconnector/NewDelete.cpp",
    "src/ports/postgres/dbconnector/NativeRandomNumberGenerator_proto.hpp",
    "src/ports/postgres/dbconnector/dbconnector.hpp",
    "src/dbal/BoostIntegration/MathToolkit_impl.hpp",
):
    path = Path(filename)
    source = path.read_text().replace("#if !_GLIBCXX_USE_CXX11_ABI", "#if __cplusplus < 201103L")
    source = source.replace("#if _GLIBCXX_USE_CXX11_ABI", "#if __cplusplus >= 201103L")
    if filename.endswith("dbconnector.hpp"):
        source = "#include <array>\n#include <tuple>\n#include <functional>\n" + source
    path.write_text(source)


replace_once(
    "src/modules/linalg/metric.cpp",
    """std::string dist_fn_name(string s)
{
    std::istringstream ss(s);
    std::string token, fname;
    if (std::getline(ss, token, '.')) fname = token; // suppose there is no schema name
    if (std::getline(ss, token, '.')) fname = token; // previous part is schema name
    return fname;
}""",
    """const char* dist_fn_name(const char* s)
{
    // Do not cross libstdc++ / PostgreSQL allocator boundaries for strings.
    const char* dot = std::strchr(s, '.');
    return dot ? dot + 1 : s;
}""",
)

metric = Path("src/modules/linalg/metric.cpp")
source = metric.read_text().replace("#include <sstream>", "#include <cstring>")
source = source.replace("string dist_fname =", "const char* dist_fname =")
source = source.replace("std::string fname =", "const char* fname =")
source = source.replace("std::string fname,", "const char* fname,")
source = source.replace('fname.compare("', 'std::strcmp(fname, "')
metric.write_text(source)

replace_once(
    "src/ports/postgres/dbconnector/FunctionHandle_impl.hpp",
    """    FunctionCallInfoBaseData funcPtrCallInfo;
    int nargs = args.numFields();
    MemSet(&funcPtrCallInfo, 0, SizeForFunctionCallInfo(nargs));""",
    """    // PG12+ uses a flexible argument array. Reserve aligned stack storage
    // for the maximum supported argument count, not just the base struct.
    LOCAL_FCINFO(callStorage, FUNC_MAX_ARGS);
    FunctionCallInfoBaseData& funcPtrCallInfo = *callStorage;
    MemSet(callStorage, 0, SizeForFunctionCallInfo(FUNC_MAX_ARGS));""",
)
