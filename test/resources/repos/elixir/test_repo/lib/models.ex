defmodule TestRepo.Models do
  @moduledoc """
  Models module demonstrating various Elixir patterns including structs, protocols, and behaviours.
  """

  defprotocol Serializable do
    @doc "Convert model to map representation"
    def to_map(model)
  end

  defmodule User do
    @type t :: %__MODULE__{
            id: String.t(),
            name: String.t() | nil,
            email: String.t(),
            roles: list(String.t())
          }

    defstruct [:id, :name, :email, roles: []]

    @doc """
    Creates a new user.

    ## Examples

        iex> TestRepo.Models.User.new("1", "Alice", "alice@example.com")
        %TestRepo.Models.User{id: "1", name: "Alice", email: "alice@example.com", roles: []}

    """
    def new(id, name, email, roles \\ []) do
      %__MODULE__{id: id, name: name, email: email, roles: roles}
    end

    @doc """
    Checks if user has a specific role.
    """
    def has_role?(%__MODULE__{roles: roles}, role) do
      role in roles
    end

    @doc """
    Adds a role to the user.
    """
    def add_role(%__MODULE__{roles: roles} = user, role) do
      %{user | roles: [role | roles]}
    end
  end

  defmodule Item do
    @type t :: %__MODULE__{
            id: String.t(),
            name: String.t(),
            price: float(),
            category: String.t()
          }

    defstruct [:id, :name, :price, :category]

    @doc """
    Creates a new item.

    ## Examples

        iex> TestRepo.Models.Item.new("1", "Widget", 19.99, "electronics")
        %TestRepo.Models.Item{id: "1", name: "Widget", price: 19.99, category: "electronics"}

    """
    def new(id, name, price, category) do
      %__MODULE__{id: id, name: name, price: price, category: category}
    end

    @doc """
    Formats price for display.
    """
    def display_price(%__MODULE__{price: price}) do
      "$#{:erlang.float_to_binary(price, decimals: 2)}"
    end

    @doc """
    Checks if item is in a specific category.
    """
    def in_category?(%__MODULE__{category: category}, target_category) do
      category == target_category
    end
  end

  defmodule Order do
    alias TestRepo.Models.{User, Item}

    @type t :: %__MODULE__{
            id: String.t(),
            user: User.t(),
            items: list(Item.t()),
            total: float(),
            status: atom()
          }

    defstruct [:id, :user, items: [], total: 0.0, status: :pending]

    @doc """
    Creates a new order.
    """
    def new(id, user, items \\ []) do
      total = calculate_total(items)
      %__MODULE__{id: id, user: user, items: items, total: total}
    end

    @doc """
    Adds an item to the order.
    """
    def add_item(%__MODULE__{items: items} = order, item) do
      new_items = [item | items]
      %{order | items: new_items, total: calculate_total(new_items)}
    end

    @doc """
    Updates order status.
    """
    def update_status(%__MODULE__{} = order, status) do
      %{order | status: status}
    end

    defp calculate_total(items) do
      Enum.reduce(items, 0.0, fn item, acc -> acc + item.price end)
    end
  end

  # Protocol implementations
  defimpl Serializable, for: User do
    def to_map(%User{id: id, name: name, email: email, roles: roles}) do
      %{id: id, name: name, email: email, roles: roles}
    end
  end

  defimpl Serializable, for: Item do
    def to_map(%Item{id: id, name: name, price: price, category: category}) do
      %{id: id, name: name, price: price, category: category}
    end
  end

  defimpl Serializable, for: Order do
    def to_map(%Order{id: id, user: user, items: items, total: total, status: status}) do
      %{
        id: id,
        user: Serializable.to_map(user),
        items: Enum.map(items, &Serializable.to_map/1),
        total: total,
        status: status
      }
    end
  end

  @doc """
  Factory function to create a sample user.
  """
  def create_sample_user do
    User.new("sample", "Sample User", "sample@example.com", ["user"])
  end

  @doc """
  Factory function to create a sample item.
  """
  def create_sample_item do
    Item.new("sample", "Sample Item", 9.99, "sample")
  end
end 