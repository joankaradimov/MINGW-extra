// Change the tempo through the application session state and read it back.
// Link stays disabled, so no sockets are opened.

#include <ableton/Link.hpp>

#include <cmath>
#include <cstdio>

int main()
{
  ableton::Link link(120.0);

  const auto now = link.clock().micros();
  auto state = link.captureAppSessionState();
  state.setTempo(97.5, now);
  link.commitAppSessionState(state);

  const auto tempo = link.captureAppSessionState().tempo();
  std::printf("tempo %.1f, enabled %d, peers %zu\n",
              tempo, link.isEnabled(), link.numPeers());

  return std::fabs(tempo - 97.5) < 1e-9 && !link.isEnabled() ? 0 : 1;
}
