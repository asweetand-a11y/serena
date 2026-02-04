defmodule TestRepoTest do
  use ExUnit.Case
  doctest TestRepo

  test "greets the world" do
    assert TestRepo.hello() == :world
  end

  test "adds numbers correctly" do
    assert TestRepo.add(2, 3) == 5
    assert TestRepo.add(-1, 1) == 0
    assert TestRepo.add(0, 0) == 0
  end
end 