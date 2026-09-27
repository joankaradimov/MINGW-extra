# A consumer of the installed library: starts the widget's default shell,
# cmd.exe, through the ConPTY backend, types a command once the prompt appears
# and waits for its output. The typed text reads ROUND^-TRIP, so ROUND-TRIP can
# only come from cmd running it.
cmake_minimum_required(VERSION 3.18)
project(check CXX)

find_package(qtermwidget6 REQUIRED)
find_package(Qt6 REQUIRED COMPONENTS Widgets)

file(WRITE "${CMAKE_BINARY_DIR}/main.cpp" [=[
#include <QApplication>
#include <QTimer>
#include <qtermwidget.h>
#include <cstdio>

int main(int argc, char **argv)
{
    QApplication app(argc, argv);
    QTermWidget term(0);
    QString seen;
    bool typed = false;

    term.setArgs({QStringLiteral("/d")});
    QObject::connect(&term, &QTermWidget::receivedData, [&](const QString &text) {
        seen += text;
        if (seen.contains(QStringLiteral("ROUND-TRIP")))
            app.exit(0);
        else if (!typed && seen.contains(QLatin1Char('>'))) {
            typed = true;
            term.sendText(QStringLiteral("echo ROUND^-TRIP\r"));
        }
    });
    QTimer::singleShot(30000, &app, [&] {
        std::fprintf(stderr, "no reply within 30 s; the terminal showed:\n%s\n",
                     qPrintable(seen));
        app.exit(1);
    });

    term.startShellProgram();
    const int status = app.exec();
    if (status == 0)
        std::puts("cmd.exe answered through ConPTY");
    return status;
}
]=])

add_executable(check "${CMAKE_BINARY_DIR}/main.cpp")
target_link_libraries(check PRIVATE qtermwidget6 Qt6::Widgets)
