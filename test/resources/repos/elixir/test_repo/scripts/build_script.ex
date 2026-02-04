defmodule TestRepo.Scripts.BuildScript do
  @moduledoc """
  Build script that references models.
  This is in the scripts directory which should be ignored in some tests.
  """

  alias TestRepo.Models.{User, Item}

  @doc """
  Script function that creates test data.
  """
  def create_test_data do
    user = User.new("script_user", "Script User", "script@example.com")
    item = Item.new("script_item", "Script Item", 1.0, "script")

    {user, item}
  end

  @doc """
  Another script function referencing User.
  """
  def cleanup_users do
    # This would reference User in a real scenario
    IO.puts("Cleaning up users...")
  end
end 