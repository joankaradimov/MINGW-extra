# A consumer of the installed modules. LXQtCompilerSettings builds a Qt
# program with the flags every LXQt project gets; lxqt_translate_ts() compiles
# a German catalogue with lrelease; lxqt_translate_desktop() merges a German
# name into one desktop file with its shell merger and into another with its
# Perl one (USE_YAML). The program then checks all three results.
cmake_minimum_required(VERSION 3.18)
project(check CXX)

find_package(lxqt2-build-tools REQUIRED)
find_package(Qt6 REQUIRED COMPONENTS Core LinguistTools)
find_package(Perl REQUIRED)
include(LXQtCompilerSettings NO_POLICY_SCOPE)
include(LXQtTranslateTs)
include(LXQtTranslateDesktop)

file(WRITE "${CMAKE_BINARY_DIR}/translations/check_de.ts" [=[<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="de">
<context>
    <name>check</name>
    <message>
        <source>Hello</source>
        <translation>Hallo</translation>
    </message>
</context>
</TS>
]=])
file(WRITE "${CMAKE_BINARY_DIR}/check.desktop.in" "[Desktop Entry]\nType=Application\nName=Check\n")
file(WRITE "${CMAKE_BINARY_DIR}/translations/check_de.desktop" "Name[de]=Prüfung\n")
file(WRITE "${CMAKE_BINARY_DIR}/yaml.desktop.in" "[Desktop Entry]\nType=Application\nName=Check\n")
file(WRITE "${CMAKE_BINARY_DIR}/translations/yaml_de.desktop.yaml" "Desktop Entry/Name: Prüfung\n")

lxqt_translate_ts(QM TEMPLATE check TRANSLATION_DIR "${CMAKE_BINARY_DIR}/translations")
lxqt_translate_desktop(DESKTOP
    SOURCES "${CMAKE_BINARY_DIR}/check.desktop.in"
    TRANSLATION_DIR "${CMAKE_BINARY_DIR}/translations")
lxqt_translate_desktop(DESKTOP_YAML USE_YAML
    SOURCES "${CMAKE_BINARY_DIR}/yaml.desktop.in"
    TRANSLATION_DIR "${CMAKE_BINARY_DIR}/translations")

file(WRITE "${CMAKE_BINARY_DIR}/main.cpp" [=[
#include <QCoreApplication>
#include <QFile>
#include <QTranslator>
#include <cstdio>

static bool hasGermanName(const char *path)
{
    QFile desktop(QString::fromLatin1(path));
    return desktop.open(QIODevice::ReadOnly) &&
           QString::fromUtf8(desktop.readAll()).contains(QStringLiteral("Name[de]=Prüfung"));
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTranslator translator;
    if (!translator.load(QStringLiteral("check_de.qm")) || !app.installTranslator(&translator))
        return std::fputs("check_de.qm did not load\n", stderr), 1;
    if (QCoreApplication::translate("check", "Hello") != QStringLiteral("Hallo"))
        return std::fputs("the catalogue does not translate Hello\n", stderr), 1;

    for (const char *desktop : {"check.desktop", "yaml.desktop"})
        if (!hasGermanName(desktop))
            return std::fprintf(stderr, "%s lacks the German name\n", desktop), 1;

    std::puts("translation and both desktop files merged");
    return 0;
}
]=])

add_executable(check "${CMAKE_BINARY_DIR}/main.cpp" ${QM} ${DESKTOP} ${DESKTOP_YAML})
target_link_libraries(check PRIVATE Qt6::Core)
